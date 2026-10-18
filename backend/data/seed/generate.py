"""`make seed`: deterministic synthetic data for both businesses and Maya's finance mailbox.

    python backend/data/seed/generate.py [--out DIR]       (default: backend/data/generated, gitignored)

Output (all synthetic, labelled as such):

    holidays.yaml                     copy of the holiday calendar config
    manifest.json                     every planted anomaly with its expected detection, the mailbox index with
                                      ground truth, and a SHA-256 of every other file (test-only; app code must
                                      never read it)
    mailbox/em-001.eml ... em-030.eml Maya's Corner Store finance mailbox (untrusted content, invariant 2)
    <business_id>/business.json       profile, accounts (number, name, statement path), sim_today
    <business_id>/counterparties.json suppliers (with bank-account history), payees, customers, staff, domains
    <business_id>/products.csv        id, name, category, unit, supplier_id, price_minor
    <business_id>/statements/{bank,wallet,cash}.csv   prompt 2 ingest columns, decimal amounts, running balance
    <business_id>/sale_lines.csv      daily product-level POS sales (refunds as negative qty)
    <business_id>/purchases.csv       supplier invoice lines with unit cost, due/paid dates, payment reference
    <business_id>/receivables.csv     customer invoices, paid or open
    <business_id>/scheduled_items.csv known open payables/receivables, overdue ones plus sim_today .. +90 days

Determinism: a fixed numpy seed per business, Faker seeded per instance, fixed dates, no wall clock, LF line
endings and stable MIME boundaries. Running it twice produces byte-identical output (tests/unit/test_seed.py).
Amounts in non-statement files are integer minor units; statement amounts are decimal strings like bank exports.
"""

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:  # allow running as a script: python backend/data/seed/generate.py
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402
import yaml  # noqa: E402
from faker import Faker  # noqa: E402

from data.seed.anomalies import ledger_anomalies  # noqa: E402
from data.seed.businesses import (  # noqa: E402
    BUSINESSES,
    HISTORY_END,
    HISTORY_START,
    PAYEE_DOMAINS,
    SCHEDULE_HORIZON_DAYS,
    SIM_TODAY,
    BusinessSpec,
)
from data.seed.mailbox import FLAGS, build_mailbox, index_entry, to_anomaly, to_eml  # noqa: E402
from data.seed.transactions import BusinessData, Holiday, generate_business, money  # noqa: E402

SEED = 20261020
GENERATOR_VERSION = 1
SEED_DIR = Path(__file__).resolve().parent
HOLIDAYS_FILE = SEED_DIR / "holidays.yaml"
DEFAULT_OUT = BACKEND / "data" / "generated"
STATEMENT_COLUMNS = ["date", "description", "amount", "balance", "counterparty", "counterparty_account",
                     "counterparty_phone", "reference", "channel", "currency"]


def load_holidays(path: Path = HOLIDAYS_FILE) -> list[Holiday]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["holidays"]
    return [Holiday(id=h["id"], key=h["key"], name=h["name"], start=h["start"], end=h["end"],
                    holiday_date=h["holiday_date"]) for h in raw]


# ---- writers ----------------------------------------------------------------------------------------------------

def _json_default(o):
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False, default=_json_default) + "\n").encode())


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([r[c] for c in columns])
    path.write_bytes(buf.getvalue().encode())


def statement_rows(rows, currency: str) -> list[dict]:
    return [{"date": r.date.isoformat(), "description": r.description, "amount": money(r.amount_minor),
             "balance": money(r.balance_minor), "counterparty": r.counterparty,
             "counterparty_account": r.counterparty_account, "counterparty_phone": r.counterparty_phone,
             "reference": r.reference, "channel": r.channel, "currency": currency} for r in rows]


# ---- per business -----------------------------------------------------------------------------------------------

ACCOUNT_NAMES = {"bank": "Operating account", "wallet": "Mobile-wallet merchant account", "cash": "Cash book"}


def business_profile(spec: BusinessSpec, data: BusinessData) -> dict:
    numbers = {"bank": spec.bank_account_number, "wallet": spec.wallet_account_number,
               "cash": spec.cash_book_number}
    openings = {"bank": spec.opening_bank_minor, "wallet": 0, "cash": spec.opening_cash_minor}
    institutions = {"bank": spec.bank_name, "wallet": spec.wallet_provider, "cash": spec.name}
    return {
        "synthetic": True, "id": spec.id, "name": spec.name, "pack": spec.pack, "currency": "USD",
        "timezone": "UTC", "sim_today": SIM_TODAY, "history": {"start": HISTORY_START, "end": HISTORY_END},
        "schedule_horizon_days": SCHEDULE_HORIZON_DAYS, "owner": {"name": spec.owner_name, "email": spec.owner_email},
        "finance_email": spec.finance_email, "domain": spec.domain, "address": data.address,
        "holiday_calendar": "../holidays.yaml",
        "accounts": [{"id": a, "name": f"{ACCOUNT_NAMES[a]} - {institutions[a]}", "kind": a,
                      "account_number": numbers[a], "statement": f"statements/{a}.csv",
                      "opening_balance_minor": openings[a]} for a in ("bank", "wallet", "cash")],
    }


def counterparties(spec: BusinessSpec, data: BusinessData) -> dict:
    payees: dict[str, dict] = {}
    for b in spec.bills:
        payees.setdefault(b.counterparty_id, {"id": b.counterparty_id, "name": b.payee, "category": b.category,
                                              "account_number": b.account_number,
                                              "email_domain": PAYEE_DOMAINS.get(b.counterparty_id, "")})
    suppliers = [{"id": s.id, "name": s.name, "domain": s.domain, "billing_email": s.billing_email,
                  "contact_name": s.contact_name,
                  "bank_accounts": [{"bank_name": s.bank_name, "account_number": s.account_number,
                                     "since": s.account_since}],
                  "terms_days": s.terms_days, "early_pay_discount_pct": s.early_pay_discount_pct * 100,
                  "early_pay_days": s.early_pay_days} for s in spec.suppliers]
    customers = [{"id": c.id, "name": c.name, "email": c.email, "domain": c.email.split("@")[1],
                  "allowlisted": c.allowlisted, "terms_days": c.terms_days} for c in spec.customers]
    known = sorted({spec.domain} | {s.domain for s in spec.suppliers} | {c["domain"] for c in customers} |
                   {p["email_domain"] for p in payees.values() if p["email_domain"]})
    return {"synthetic": True, "owner": {"name": spec.owner_name, "email": spec.owner_email},
            "suppliers": suppliers, "payees": list(payees.values()), "customers": customers,
            "staff": data.staff, "wallet_provider": spec.wallet_provider, "known_domains": known}


def write_business(out: Path, spec: BusinessSpec, data: BusinessData) -> None:
    root = out / spec.id
    write_json(root / "business.json", business_profile(spec, data))
    write_json(root / "counterparties.json", counterparties(spec, data))
    write_csv(root / "products.csv", ["id", "name", "category", "unit", "supplier_id", "price_minor"],
              [{"id": p.id, "name": p.name, "category": p.category, "unit": p.unit, "supplier_id": p.supplier_id,
                "price_minor": p.price_minor} for p in spec.products])
    for acct, rows in data.statements.items():
        write_csv(root / "statements" / f"{acct}.csv", STATEMENT_COLUMNS, statement_rows(rows, "USD"))
    write_csv(root / "sale_lines.csv", ["id", "date", "product_id", "qty", "unit_price_minor", "revenue_minor",
                                        "cost_minor"], data.sale_lines)
    write_csv(root / "purchases.csv", ["id", "invoice_id", "supplier_id", "invoice_date", "due_date", "product_id",
                                       "qty", "unit_cost_minor", "line_total_minor", "paid_on",
                                       "payment_reference", "early_pay_discount_pct", "discount_deadline"],
              data.purchases)
    write_csv(root / "receivables.csv", ["id", "customer_id", "issue_date", "due_date", "amount_minor", "status",
                                         "paid_on", "payment_reference"], data.receivables)
    write_csv(root / "scheduled_items.csv", ["id", "kind", "category", "due_date", "amount_minor", "status",
                                             "counterparty_id", "source", "reference"], data.scheduled_items)


# ---- main -------------------------------------------------------------------------------------------------------

def _prepare(out: Path) -> None:
    """Only ever delete a directory this generator created (it holds our manifest) or an empty one."""
    if out.exists():
        if any(out.iterdir()) and not (out / "manifest.json").exists():
            raise SystemExit(f"refusing to overwrite {out}: not a seed output directory")
        shutil.rmtree(out)
    out.mkdir(parents=True)


def generate(out: Path = DEFAULT_OUT) -> dict:
    """Generate everything into `out` (replaced) and return the manifest."""
    out = Path(out)
    _prepare(out)
    holidays = load_holidays()
    shutil.copyfile(HOLIDAYS_FILE, out / "holidays.yaml")
    anomalies: list[dict] = []
    datasets: dict[str, BusinessData] = {}
    for i, spec in enumerate(BUSINESSES):
        fake = Faker("en_US")
        fake.seed_instance(SEED + i)
        data = generate_business(spec, holidays, np.random.default_rng([SEED, i]), fake)
        datasets[spec.id] = data
        write_business(out, spec, data)
        anomalies += ledger_anomalies(data, holidays)

    maya = datasets["maya_corner_store"]
    mails = build_mailbox(maya)
    for m in mails:
        (out / "mailbox").mkdir(exist_ok=True)
        (out / "mailbox" / f"{m.id}.eml").write_bytes(to_eml(m))
        if m.attack:
            anomalies.append(to_anomaly(m, maya.spec.id))

    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {
        "synthetic": True,
        "generator": {"version": GENERATOR_VERSION, "seed": SEED, "faker_locale": "en_US"},
        "sim_today": SIM_TODAY, "history": {"start": HISTORY_START, "end": HISTORY_END},
        "holiday_calendar": "holidays.yaml",
        "businesses": [{"id": s.id, "name": s.name, "pack": s.pack, "dir": s.id} for s in BUSINESSES],
        "flag_vocabulary": FLAGS,
        "anomalies": anomalies,
        "mailbox": {"business_id": maya.spec.id, "count": len(mails), "emails": [index_entry(m) for m in mails]},
        "files": files,
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    manifest = generate(args.out)
    digest = hashlib.sha256((args.out / "manifest.json").read_bytes()).hexdigest()
    attacks = sum(a["category"] == "attack" for a in manifest["anomalies"])
    print(f"seed written to {args.out}: {len(manifest['files'])} files, {len(manifest['anomalies'])} anomalies "
          f"({attacks} mailbox attacks), {manifest['mailbox']['count']} emails")
    print(f"manifest sha256 {digest}")


if __name__ == "__main__":
    main()
