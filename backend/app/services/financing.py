"""Financing match, Readiness Passport and Passport exports for one business.

`financing_facts` runs inside services.finance.compute, so the match, the Passport and every number they show are
Facts in the same store the API and the planner read (invariant 4).

`prepare_loan_draft` builds a draft application (engine.application) for an eligible product at a repayment-safe
amount, exporting the Passport it cites, and saves it in the gateway's draft store. Both the owner's UI and the
planner's tool use it; neither can send it: only the gateway executes `submit_loan_application`, after the owner
signs.

`PassportExports` stores each exported Passport as its canonical JSON bytes under
`<tenant>/passports/<sha256>.json` and appends `passport.exported` with the hash to the audit log (invariant 7).
Prompt 17's anchoring batches those hashes; anyone holding the file can recompute the hash and check it (invariant 9).
"""

import json
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from app.audit import AuditLog
from app.audit.canonical import canonical_json, sha256_hex
from app.clock import Clock
from app.engine.application import build_draft
from app.engine.catalog import Catalog, load_catalog
from app.engine.financing import FinancingMatch, financing_metrics, match_financing
from app.engine.passport import Passport, build_passport, passport_document
from app.engine.readiness_factors import readiness_raw_facts
from app.firewall.digit_check import PLACEHOLDER_RE
from app.firewall.store import FactStore
from app.gateway.drafts import LoanDraftStore
from app.ledger.documents import Receivable, SupplierInvoice
from app.ledger.snapshot import LedgerSnapshot
from app.packs.readiness import ReadinessResult, readiness_score
from app.packs.schema import Pack


@dataclass(frozen=True)
class FinancingResult:
    match: FinancingMatch
    passport: Passport
    readiness: ReadinessResult


def financing_facts(*, store: FactStore, snapshot: LedgerSnapshot, pack: Pack, clock: Clock,
                    receivables: tuple[Receivable, ...], supplier_invoices: tuple[SupplierInvoice, ...],
                    business_id: str, business_name: str, synthetic_data: bool,
                    catalog: Catalog | None = None) -> FinancingResult:
    """Add readiness, financing and Passport facts to `store` (which must already hold the core facts)."""
    catalog = catalog or load_catalog()
    raw = readiness_raw_facts(snapshot, pack, clock, store.get("cash.buffer_days"), receivables, supplier_invoices)
    store.add_all(raw.values())
    readiness = readiness_score(raw, pack)
    store.add_all([readiness.score, *readiness.factor_scores.values()])
    store.add_all(financing_metrics(snapshot, pack, clock))
    pool = {f.id: f for f in store}
    match, match_facts = match_financing(pool, pack, clock, catalog, snapshot.currency)
    store.add_all(match_facts)
    passport, passport_facts = build_passport(
        raw=raw, readiness=readiness, match=match, pack=pack, as_of=clock.today(),
        business_id=business_id, business_name=business_name, currency=snapshot.currency,
        synthetic_data=synthetic_data)
    store.add_all(passport_facts)
    return FinancingResult(match=match, passport=passport, readiness=readiness)


class PassportExport(BaseModel):
    """One exported Passport: `sha256` is the SHA-256 of the canonical JSON of `document`."""

    business_id: str
    as_of: date
    sha256: str
    band_id: str
    document: dict


class PassportExportSummary(BaseModel):
    business_id: str
    as_of: date
    sha256: str
    band_id: str


class PassportExports:
    """Write-once store of exported Passports for one tenant, named by content hash."""

    def __init__(self, folder: Path):
        self.folder = folder
        self._lock = threading.Lock()

    def export(self, business_id: str, result: FinancingResult, store: FactStore, audit: AuditLog) -> PassportExport:
        doc = passport_document(result.passport, result.match, store)
        data = canonical_json(doc)
        digest = sha256_hex(data)
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{digest}.json"
            if not path.exists():
                path.write_bytes(data)
        audit.append("passport.exported", {
            "business_id": business_id, "sha256": digest, "as_of": doc["as_of"], "band": doc["band"]["id"],
            "schema": doc["schema"], "bytes": len(data),
        })
        return PassportExport(business_id=business_id, as_of=result.passport.as_of, sha256=digest,
                              band_id=result.passport.band_id, document=doc)

    def get(self, sha256: str) -> PassportExport | None:
        """A stored export, only if its bytes still hash to its name (a tampered file is reported as missing)."""
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            return None
        path = self.folder / f"{sha256}.json"
        if not path.is_file():
            return None
        data = path.read_bytes()
        if sha256_hex(data) != sha256:
            return None
        doc = json.loads(data)
        return PassportExport(business_id=doc["business"]["id"], as_of=date.fromisoformat(doc["as_of"]),
                              sha256=sha256, band_id=doc["band"]["id"], document=doc)

    def list(self) -> list[PassportExportSummary]:
        out = []
        for path in sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []:
            item = self.get(path.stem)
            if item is not None:
                out.append(PassportExportSummary(**item.model_dump(exclude={"document"})))
        return sorted(out, key=lambda e: (e.as_of, e.sha256))


class LoanDraft(BaseModel):
    draft_id: str
    sha256: str
    passport_sha256: str
    document: dict


def prepare_loan_draft(*, business_id: str, result: FinancingResult, store: FactStore, exports: PassportExports,
                       drafts: LoanDraftStore, audit: AuditLog, product_id: str,
                       amount_minor: int | None = None) -> LoanDraft:
    """Build and store a draft for `product_id` at `amount_minor` (default: the repayment-safe amount).

    Raises engine.application.DraftError(rule) if the product is unknown, not eligible, or the amount is outside
    [product minimum, repayment-safe amount]. The refusal is logged too.
    """
    m = next((p for p in result.match.products if p.product_id == product_id), None)
    amount = amount_minor if amount_minor is not None else (store.get(m.safe_amount_fact_id).value if m else 0)
    exported = exports.export(business_id, result, store, audit)
    try:
        draft_id, digest, doc = build_draft(match=result.match, passport=result.passport,
                                            passport_sha256=exported.sha256, store=store, catalog=load_catalog(),
                                            product_id=product_id, amount_minor=amount)
    except Exception as exc:
        rule = getattr(exc, "rule", "invalid_request")
        audit.append("financing.draft_refused", {"business_id": business_id, "product_id": product_id,
                                                 "amount_minor": amount, "rule": rule})
        raise
    drafts.save(draft_id, doc)
    audit.append("financing.draft_prepared", {
        "business_id": business_id, "draft_id": draft_id, "sha256": digest, "product_id": product_id,
        "amount_minor": amount, "passport_sha256": exported.sha256,
    })
    return LoanDraft(draft_id=draft_id, sha256=digest, passport_sha256=exported.sha256, document=doc)


def referenced_fact_ids(result: FinancingResult) -> list[str]:
    """Every fact the match and the Passport cite, by ID field or by placeholder, so a response can carry them."""
    ids: set[str] = set()
    texts: list[str] = [*result.passport.reasons, *(s.text for s in result.passport.path_to_eligibility)]
    m = result.match
    ids.update([m.max_installment_fact_id, *m.capacity_fact_ids, result.passport.score_fact_id])
    for p in m.products:
        ids.update([p.min_amount_fact_id, p.max_amount_fact_id, p.safe_amount_fact_id, p.installment_fact_id,
                    p.total_cost_fact_id, p.term_fact_id, p.monthly_rate_fact_id])
        for r in p.rules:
            ids.update([r.metric_fact_id, r.threshold_fact_id])
            if r.eligible_from_fact_id:
                ids.add(r.eligible_from_fact_id)
            texts.append(r.reason)
    for f in result.passport.factors:
        ids.update([f.raw_fact_id, f.score_fact_id, f.weight_fact_id])
        texts.append(f.reason)
    for t in texts:
        ids.update(PLACEHOLDER_RE.findall(t))
    return sorted(ids)


def verify_passport_bytes(data: bytes) -> str:
    """The SHA-256 a verifier gets for a Passport file: re-serialize canonically, then hash."""
    return sha256_hex(canonical_json(json.loads(data)))
