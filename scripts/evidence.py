"""`make evidence`: collect the execution evidence into docs/evidence/, with an index.md that explains each file.

Offline and read-only (works with LLM_REPLAY=replay and no network): it reads the dev data in backend/data/tenants
and backend/data/sandboxpay straight from disk (SQLite opened read-only, the audit log copied up to its last complete
line), so it never appends to the audit log and can run while the app is up. Nothing here is typed by hand
(invariant 8): every number in the index is read from the files written next to it.

- audit_log.jsonl + audit_verify.json: the hash-chained audit log and its chain verification, plus a check that every
  anchored audit head in anchors.json is the hash of that entry in this log.
- anchors.json + anchors_verify.json: the live testnet anchors written by `make anchor`, re-verified offline from the
  chain responses recorded under backend/data/replay/rpc/ (Merkle proofs fold into the root; the recorded transaction
  is a confirmed 0-value self-transaction on an allow-listed testnet carrying exactly that root).
- redteam.json + benign.json: the red-team report written by `make redteam`, and its benign tasks per provider.
- tests.json: pass/fail/skip counts per suite from a fresh pytest run in replay mode (skip with --no-tests).
- outbox/<business>.json and payments/: every email sent or simulated per business, each business's payment requests
  with their status history, and SandboxPay's own payment log.
- llm_spend.json: LLM spend from the local spend counter, from the audit log's llm.call entries and from the token
  usage of every replay recording (what it cost to record each set).
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

DATA = BACKEND / "data" / "tenants"
SANDBOXPAY = BACKEND / "data" / "sandboxpay" / "sandboxpay.sqlite"
REPLAY = BACKEND / "data" / "replay"
RESULTS = ROOT / "docs" / "results"
OUT = ROOT / "docs" / "evidence"
REPLAY_SETS = {"openai": REPLAY / "llm", "openai-demo": REPLAY / "openai-demo" / "llm",
               "gemini": REPLAY / "gemini" / "llm"}


def venv_python() -> str:
    win = BACKEND / ".venv" / "Scripts" / "python.exe"
    nix = BACKEND / ".venv" / "bin" / "python"
    return str(win if win.exists() else nix if nix.exists() else sys.executable)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def git_commit() -> str | None:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        return head.stdout.strip() + ("+dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return None


# ---- Audit log --------------------------------------------------------------------------------------------------

def export_audit(anchors: dict | None) -> dict:
    """Snapshot the log up to its last complete line (the app may be appending), verify the chain, and check every
    anchored audit head against the entry at that sequence number."""
    from app.audit.log import AuditLog

    src, dest = DATA / "audit.jsonl", OUT / "audit_log.jsonl"
    if not src.is_file():
        return {"present": False, "reason": f"no audit log at {rel(src)}: run the app (make dev or make demo) first"}
    raw = src.read_bytes()
    dest.write_bytes(raw[: raw.rfind(b"\n") + 1])
    result = AuditLog(dest, clock=None).verify()
    by_seq = {}
    kinds: Counter[str] = Counter()
    for line in dest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            by_seq[entry["seq"]] = entry["hash"]
            kinds[entry["kind"]] += 1
    heads = []
    for batch in (anchors or {}).get("batches", []):
        for leaf in batch["leaves"]:
            if leaf["kind"] == "audit_head":
                seq = batch["head_seq"]
                heads.append({"batch_id": batch["batch_id"], "seq": seq, "anchored_hash": leaf["hash"],
                              "matches_log": by_seq.get(seq) == leaf["hash"]})
    return {
        "present": True, "source": rel(src), "file": "audit_log.jsonl", "chain_ok": result.ok,
        "entries": result.entries, "head": result.head.model_dump(), "first_bad_seq": result.first_bad_seq,
        "reason": result.reason, "entries_by_kind": dict(sorted(kinds.items())),
        "anchored_heads_checked": len(heads), "anchored_heads_matching": sum(h["matches_log"] for h in heads),
        "anchored_heads": heads,
    }


# ---- Anchors ----------------------------------------------------------------------------------------------------

def verify_anchors(anchors: dict | None) -> dict:
    """Re-verify every anchored batch from the recorded chain responses, with no network."""
    from app.anchoring.chain import CachedChain
    from app.anchoring.merkle import ProofStep, build, leaf_hash, verify_proof
    from app.config import ANCHOR_CHAIN_ALLOWLIST
    from app.llm.cache import ReplayMiss, RequestCache

    if anchors is None:
        return {"present": False, "reason": "no docs/results/anchors.json: run `make anchor`"}
    out = []
    for batch in anchors["batches"]:
        leaves = [leaf_hash(leaf["kind"], leaf["hash"]) for leaf in batch["leaves"]]
        root, _ = build(leaves)
        proofs_ok = root == batch["merkle_root"] and all(
            leaf["leaf_hash"] == h and verify_proof(h, [ProofStep(**s) for s in leaf["proof"]], root)
            for leaf, h in zip(batch["leaves"], leaves))
        check = {"batch_id": batch["batch_id"], "tx_hash": batch["tx_hash"], "explorer_url": batch["explorer_url"],
                 "block_number": batch["block_number"], "leaves": Counter(l["kind"] for l in batch["leaves"]),
                 "merkle_proofs_ok": proofs_ok}
        try:
            tx = CachedChain(RequestCache(REPLAY, "replay"), batch["chain_id"]).get_tx(batch["tx_hash"])
            check.update(
                recorded_tx=True, data_is_root=tx.data_hex == root, value_wei=tx.value_wei,
                self_transaction=tx.to_address.lower() == tx.from_address.lower(), succeeded=tx.succeeded,
                allow_listed_chain=tx.chain_id in ANCHOR_CHAIN_ALLOWLIST, block_matches=tx.block_number ==
                batch["block_number"])
            check["ok"] = proofs_ok and check["data_is_root"] and tx.value_wei == 0 and check["self_transaction"] \
                and tx.succeeded and check["allow_listed_chain"] and check["block_matches"]
        except ReplayMiss:
            check.update(recorded_tx=False, ok=False)
        out.append(check)
    return {"present": True, "chain_id": anchors["chain_id"], "chain_name": anchors.get("chain_name"),
            "verified_log_ok_at_anchor_time": anchors["verified_log_ok"], "batches_checked": len(out),
            "batches_ok": sum(c["ok"] for c in out), "batches": out}


# ---- Tests ------------------------------------------------------------------------------------------------------

def run_tests() -> dict:
    """The full pytest suite in replay mode (no keys, no network), counted per suite folder from JUnit XML."""
    env = {**os.environ, "LLM_REPLAY": "replay"}
    env.pop("REPLAY_PROVIDER", None)
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        code = subprocess.run([venv_python(), "-m", "pytest", "-c", "pyproject.toml", "--rootdir", ".", "-q",
                               "-p", "no:cacheprovider", f"--junitxml={xml}", "tests"], cwd=BACKEND, env=env,
                              capture_output=True, text=True)
        suites: dict[str, Counter] = defaultdict(Counter)
        if xml.exists():
            for case in ET.parse(xml).getroot().iter("testcase"):
                parts = (case.get("classname") or "").split(".")
                suite = parts[1] if len(parts) > 2 and parts[0] == "tests" else "other"
                tags = {child.tag for child in case}
                outcome = "failed" if "failure" in tags else "error" if "error" in tags else \
                    "skipped" if "skipped" in tags else "passed"
                suites[suite][outcome] += 1
    total = sum((c for c in suites.values()), Counter())
    checks = {}
    for name, script in (("branding", "check_branding.py"), ("frontend_types_in_sync", "gen_frontend_types.py")):
        args = [venv_python(), str(ROOT / "scripts" / script)] + (["--check"] if "types" in script else [])
        checks[name] = subprocess.run(args, cwd=ROOT, capture_output=True, text=True).returncode == 0
    return {"ran": True, "mode": "replay", "pytest_exit_code": code.returncode,
            "summary_line": (code.stdout.strip().splitlines() or [""])[-1],
            "total": dict(total), "by_suite": {k: dict(v) for k, v in sorted(suites.items())}, "checks": checks}


# ---- Outbox and payments ----------------------------------------------------------------------------------------

def businesses() -> list[str]:
    return sorted(p.name for p in DATA.iterdir() if p.is_dir() and (p / "gateway.sqlite").exists()) \
        if DATA.is_dir() else []


def export_outbox(business: str) -> dict:
    path = DATA / business / "sandbox_mailbox.sqlite"
    rows = []
    if path.exists():
        with read_only(path) as conn:
            for r in conn.execute("SELECT id, kind, recipient_id, on_date, details FROM outbox ORDER BY id"):
                details = json.loads(r["details"] or "{}")
                rows.append({"id": r["id"], "kind": r["kind"], "recipient_id": r["recipient_id"],
                             "on_date": r["on_date"], "transport": details.pop("transport", "sandbox"), **details})
    return {"business": business, "emails": len(rows),
            "by_transport": dict(Counter(r["transport"] for r in rows)), "outbox": rows}


def export_payments(business: str) -> dict:
    path = DATA / business / "payments.sqlite"
    if not path.exists():
        return {"business": business, "requests": 0, "by_status": {}, "payments": []}
    with read_only(path) as conn:
        events = defaultdict(list)
        for e in conn.execute("SELECT request_id, on_date, status, note FROM events ORDER BY seq"):
            events[e["request_id"]].append({"on_date": e["on_date"], "status": e["status"], "note": e["note"]})
        reqs = [{**dict(r), "receipt": json.loads(r["receipt"]) if r["receipt"] else None,
                 "events": events[r["id"]]} for r in conn.execute("SELECT * FROM requests ORDER BY created_on, id")]
    for r in reqs:
        r.pop("account_token", None)  # a token, but the evidence does not need it; last4 identifies the account
    return {"business": business, "requests": len(reqs), "by_status": dict(Counter(r["status"] for r in reqs)),
            "payments": reqs}


def export_sandboxpay() -> dict:
    if not SANDBOXPAY.exists():
        return {"present": False, "reason": f"no {rel(SANDBOXPAY)}: SandboxPay has not run"}
    with read_only(SANDBOXPAY) as conn:
        payments = [dict(r) for r in conn.execute(
            "SELECT id, connection_id, idempotency_key, payee_ref, payee_name, amount_minor, currency, reference, "
            "status, failure_reason, created_at, settled_at, webhook_attempts, webhook_delivered FROM payments "
            "ORDER BY created_at")]
        connections = [dict(r) for r in conn.execute(
            "SELECT id, scopes, per_payment_cap, daily_cap, currency, created_at, revoked_at FROM connections")]
    return {"present": True, "source": rel(SANDBOXPAY), "connections": connections, "payments": payments,
            "by_status": dict(Counter(p["status"] for p in payments))}


# ---- LLM spend --------------------------------------------------------------------------------------------------

def llm_spend() -> dict:
    from app.llm.pricing import cost_microusd, price_for
    from app.llm.types import Usage

    counter_file = DATA / "llm_spend.json"
    counter = json.loads(counter_file.read_text(encoding="utf-8")) if counter_file.exists() else None

    live: dict[str, Counter] = defaultdict(Counter)
    log = OUT / "audit_log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line) if line.strip() else {}
            if entry.get("kind") == "llm.call":
                d = entry["data"]
                key = f"{d['provider']}/{d['model']}"
                live[key]["calls"] += 1
                live[key][f"cache_{d['cache']}"] += 1
                live[key]["cost_microusd"] += d.get("cost_microusd", 0)

    recorded = {}
    for name, folder in REPLAY_SETS.items():
        by_model: dict[str, Counter] = defaultdict(Counter)
        for f in sorted(folder.glob("*.json")):
            resp = json.loads(f.read_text(encoding="utf-8"))
            role = resp.get("request", {}).get("role", "?")
            model = resp["response"]["model"]
            usage = Usage.model_validate(resp["response"]["completion"]["usage"])
            c = by_model[f"{role}:{resp['response']['provider']}/{model}"]
            c["recordings"] += 1
            c["input_tokens"] += usage.input_tokens
            c["cached_input_tokens"] += usage.cached_input_tokens
            c["output_tokens"] += usage.output_tokens
            c["cost_microusd"] += cost_microusd(model, usage)
            c["price_known"] = int(price_for(model)[1])
        recorded[name] = {"folder": rel(folder), "recordings": sum(c["recordings"] for c in by_model.values()),
                          "all_prices_known": all(c["price_known"] for c in by_model.values()),
                          "cost_usd": round(sum(c["cost_microusd"] for c in by_model.values()) / 1e6, 4),
                          "by_role_model": {k: dict(v) for k, v in sorted(by_model.items())}}
    return {
        "note": "Three views, none of them a provider invoice. The counter is cumulative for the dev app only (test "
                "runs keep their own counters). The audit view covers the app's own log. The recording view is what "
                "the current recordings cost to make, priced from llm/pricing.py; re-recorded cases replaced older "
                "files, so it is a lower bound of everything ever spent on recordings. A model missing from llm/pricing.py "
                "(price_known 0) is priced at the highest known rate, so its figure is an upper bound.",
        "local_counter": {"file": rel(counter_file), "spent_usd": {k: round(v / 1e6, 4) for k, v in
                                                                   counter["spent_microusd"].items()}}
        if counter else None,
        "audit_log_llm_calls": {k: {**dict(v), "cost_usd": round(v["cost_microusd"] / 1e6, 4)}
                                for k, v in sorted(live.items())},
        "replay_recordings": recorded,
    }


# ---- Index ------------------------------------------------------------------------------------------------------

def index_md(meta: dict, audit: dict, anchors: dict, anchors_check: dict, redteam: dict | None, tests: dict,
             outboxes: list[dict], payments: list[dict], sandboxpay: dict, spend: dict) -> str:
    L = ["# Execution evidence", "",
         f"Generated by `make evidence` (`scripts/evidence.py`) at {meta['generated_at']} from commit "
         f"`{meta['commit']}`. All data is synthetic (Maya's Corner Store, Lina's Boutique and any businesses created "
         "by onboarding rehearsals). Every number below is read from the file it links to; nothing is typed by hand.",
         "", "Regenerate: `make evidence` (offline, replay mode, no network). Refresh the inputs first with "
         "`make redteam` and `make anchor` when they are stale.", "", "## Files", "",
         "| File | What it is | Headline |", "|---|---|---|"]
    if audit["present"]:
        L.append(f"| [audit_log.jsonl](audit_log.jsonl) | The hash-chained audit log (invariant 7), copied from "
                 f"`{audit['source']}` | {audit['entries']} entries, head #{audit['head']['seq']} |")
        L.append(f"| [audit_verify.json](audit_verify.json) | Chain verification of that copy, entry counts by kind, "
                 f"and each anchored audit head checked against the log | chain ok: **{audit['chain_ok']}**; "
                 f"anchored heads matching: {audit['anchored_heads_matching']}/{audit['anchored_heads_checked']} |")
    else:
        L.append(f"| audit_log.jsonl | not exported: {audit['reason']} | — |")
    if anchors_check["present"]:
        L.append(f"| [anchors.json](anchors.json) | Live {anchors_check['chain_name']} anchors from `make anchor` "
                 f"(copy of `docs/results/anchors.json`): Merkle roots of hashes only, in 0-value self-transactions "
                 f"| {anchors_check['batches_checked']} batches |")
        L.append(f"| [anchors_verify.json](anchors_verify.json) | Every batch re-verified offline from the recorded "
                 f"chain responses in `backend/data/replay/rpc/` | {anchors_check['batches_ok']}/"
                 f"{anchors_check['batches_checked']} batches verify |")
    else:
        L.append(f"| anchors.json | {anchors_check['reason']} | — |")
    if redteam:
        for name, p in redteam["providers"].items():
            if p.get("status") == "ran":
                scope = "all suites" if p.get("scope", "full") == "full" else "subset: " + ", ".join(
                    f"`{s}`" for s in p.get("scope", []))
                L.append(f"| [redteam.json](redteam.json) `{name}` | Red-team and benign suites replayed from the "
                         f"`{name}` recordings (profile `{p.get('profile', '?')}`), {scope} | attacks blocked "
                         f"{p['attacks_blocked']}/{p['attacks_run']} (variants {p['attack_variants_blocked']}/"
                         f"{p['attack_variants_run']}, {p['live_llm_variants']} driven by the live planner); benign "
                         f"tasks {p['tasks_succeeded']}/{p['tasks_run']} |")
            else:
                L.append(f"| redteam.json `{name}` | not run: {p.get('reason')} | — |")
        L.append("| [benign.json](benign.json) | The benign owner tasks from redteam.json, per provider | see "
                 "redteam rows |")
    if tests.get("ran"):
        t = tests["total"]
        L.append(f"| [tests.json](tests.json) | Full pytest run in replay mode, counted per suite; plus the branding "
                 f"and frontend-types checks | {t.get('passed', 0)} passed, {t.get('failed', 0)} failed, "
                 f"{t.get('error', 0)} errors, {t.get('skipped', 0)} skipped; branding "
                 f"{'ok' if tests['checks']['branding'] else 'FAILED'}, types "
                 f"{'in sync' if tests['checks']['frontend_types_in_sync'] else 'OUT OF SYNC'} |")
    else:
        L.append(f"| [tests.json](tests.json) | {tests.get('reason')} | — |")
    for o in outboxes:
        L.append(f"| [outbox/{o['business']}.json](outbox/{o['business']}.json) | Every email sent or simulated for "
                 f"`{o['business']}` (full body; transport says Gmail or sandbox) | {o['emails']} email(s) "
                 f"{o['by_transport'] or ''} |")
    for p in payments:
        L.append(f"| [payments/{p['business']}.json](payments/{p['business']}.json) | Payment requests for "
                 f"`{p['business']}` with status history and receipts | {p['requests']} requests "
                 f"{p['by_status'] or ''} |")
    if sandboxpay["present"]:
        L.append(f"| [payments/sandboxpay.json](payments/sandboxpay.json) | SandboxPay's own payment log (the "
                 f"simulated provider's side) | {len(sandboxpay['payments'])} payments {sandboxpay['by_status'] or ''}"
                 f", {len(sandboxpay['connections'])} connections |")
    else:
        L.append(f"| payments/sandboxpay.json | {sandboxpay['reason']} | — |")
    rec = spend["replay_recordings"]
    L.append(f"| [llm_spend.json](llm_spend.json) | LLM spend three ways: local counter, the audit log's `llm.call` "
             f"entries, and the cost of the current recordings | recordings: "
             + ", ".join(f"{k} ${v['cost_usd']}{'' if v['all_prices_known'] else ' (upper bound: model not in pricing.py)'}"
                         f" ({v['recordings']} files)" for k, v in rec.items()) + " |")
    L += ["", "## How to check it yourself", "",
          "- Chain: `AuditLog(path, clock=None).verify()` in `backend/app/audit/log.py` recomputes every hash and link "
          "of `audit_log.jsonl`.",
          "- Anchors: open any `explorer_url` in `anchors.json`; the transaction's input data is the `merkle_root`. "
          "Recompute the root from the leaves with `backend/app/anchoring/merkle.py`.",
          "- Red team: `make redteam` replays every recorded case and rewrites `docs/results/redteam.json`.", ""]
    return "\n".join(L)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-tests", action="store_true", help="skip the pytest run (tests.json says so)")
    args = parser.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    meta = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "commit": git_commit()}

    anchors_file, redteam_file = RESULTS / "anchors.json", RESULTS / "redteam.json"
    anchors = json.loads(anchors_file.read_text(encoding="utf-8")) if anchors_file.exists() else None
    redteam = json.loads(redteam_file.read_text(encoding="utf-8")) if redteam_file.exists() else None

    audit = export_audit(anchors)
    write_json(OUT / "audit_verify.json", audit)
    if anchors:
        shutil.copyfile(anchors_file, OUT / "anchors.json")
    anchors_check = verify_anchors(anchors)
    write_json(OUT / "anchors_verify.json", anchors_check)
    if redteam:
        shutil.copyfile(redteam_file, OUT / "redteam.json")
        write_json(OUT / "benign.json", {
            "source": "docs/results/redteam.json", "commit": redteam.get("commit"),
            "providers": {k: {"tasks_run": v.get("tasks_run"), "tasks_succeeded": v.get("tasks_succeeded"),
                              "tasks": v.get("tasks", [])} for k, v in redteam["providers"].items()
                          if v.get("status") == "ran"}})

    print("make evidence: running the test suite in replay mode..." if not args.no_tests else
          "make evidence: tests skipped (--no-tests)")
    tests = {"ran": False, "reason": "skipped with --no-tests"} if args.no_tests else run_tests()
    write_json(OUT / "tests.json", tests)

    outboxes = [export_outbox(b) for b in businesses()]
    for o in outboxes:
        write_json(OUT / "outbox" / f"{o['business']}.json", o)
    payments = [export_payments(b) for b in businesses()]
    for p in payments:
        write_json(OUT / "payments" / f"{p['business']}.json", p)
    sandboxpay = export_sandboxpay()
    write_json(OUT / "payments" / "sandboxpay.json", sandboxpay)
    spend = llm_spend()
    write_json(OUT / "llm_spend.json", spend)

    (OUT / "index.md").write_text(index_md(meta, audit, anchors or {}, anchors_check, redteam, tests, outboxes,
                                           payments, sandboxpay, spend), encoding="utf-8", newline="\n")
    print(f"make evidence: wrote {rel(OUT)}/ (index.md explains each file)")
    ok = (not audit["present"] or audit["chain_ok"]) and \
        (not anchors_check["present"] or anchors_check["batches_ok"] == anchors_check["batches_checked"]) and \
        (not tests.get("ran") or tests["pytest_exit_code"] == 0)
    if not ok:
        print("make evidence: a check FAILED; see audit_verify.json, anchors_verify.json and tests.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
