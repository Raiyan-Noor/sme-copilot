"""Ledger-side planted anomalies, computed from the generated data so the manifest can never drift from it.

Each entry: id, business_id, category (leak | receivable | seasonality | schedule | inventory), kind, a summary,
`evidence` (statement references, row IDs, or a file + filter for large sets) and `expected_detection` naming the
component and detector that must find it. Amounts are integer minor units. Test-only ground truth: application
code must never read the manifest (it would hand the agent the answers).
"""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

from data.seed.businesses import HISTORY_END, HISTORY_START, SIM_TODAY
from data.seed.transactions import BusinessData, Holiday, daterange

HISTORY_DAYS = (HISTORY_END - HISTORY_START).days + 1
POLICY = Path(__file__).resolve().parents[2] / "app" / "gateway" / "policy.yaml"


def annualize(total: int) -> int:
    return int(round(total * 365 / HISTORY_DAYS))


def reminder_cap_minor() -> int:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    return int(policy["tiers"]["T2"]["tools"]["send_invoice_reminder"]["max_invoice_minor"])


def ledger_anomalies(data: BusinessData, holidays: list[Holiday]) -> list[dict]:
    s = data.spec
    biz = s.id
    out: list[dict] = []
    pre = s.ref_prefix
    suppliers = {sup.id: sup for sup in s.suppliers}

    # Supplier price creep (rice for the grocery, denim for the boutique).
    for p in s.products:
        if not p.cost_creep_monthly:
            continue
        lines = [ln for ln in data.purchases if ln["product_id"] == p.id]
        first, last = lines[0]["unit_cost_minor"], lines[-1]["unit_cost_minor"]
        qty = sum(ln["qty"] for ln in lines)
        out.append({
            "id": f"{pre}-LEAK-PRICE-CREEP-{p.id}", "business_id": biz, "category": "leak",
            "kind": "supplier_price_creep",
            "summary": f"{p.name} unit cost from {suppliers[p.supplier_id].name} rises steadily while the shelf "
                       "price stays fixed",
            "facts": {"supplier_id": p.supplier_id, "product_id": p.id, "first_unit_cost_minor": first,
                      "last_unit_cost_minor": last, "pct_change": round((last - first) / first * 100, 1),
                      "price_minor": p.price_minor, "invoices": len(lines),
                      "yearly_impact_minor": annualize((last - first) * qty)},
            "evidence": {"file": "purchases.csv", "row_ids": [ln["id"] for ln in lines]},
            "expected_detection": {"component": "packs.leaks", "detector": "supplier_price_creep",
                                   "subject": {"supplier_id": p.supplier_id, "product_id": p.id}},
        })

    # Duplicate subscriptions: two series to the same payee for the same amount.
    by_payee = defaultdict(list)
    for b in s.bills:
        if b.category == "software_subscriptions":
            by_payee[(b.counterparty_id, b.amount_minor)].append(b)
    for (payee, amount), bills in by_payee.items():
        if len(bills) < 2:
            continue
        refs = {b.id: data.tags.get(f"bill:{b.id}", []) for b in bills}
        out.append({
            "id": f"{pre}-LEAK-DUPLICATE-SUBSCRIPTION-{payee.removeprefix('pay_').upper()}", "business_id": biz,
            "category": "leak", "kind": "duplicate_subscription",
            "summary": f"Two {bills[0].payee} subscriptions billed every month for the same amount",
            "facts": {"counterparty_id": payee, "monthly_amount_minor": amount, "series": [b.id for b in bills],
                      "duplicate_since": min(b.start for b in bills if b.start).isoformat(),
                      "yearly_impact_minor": 12 * amount},
            "evidence": {"file": "statements/bank.csv", "references": refs},
            "expected_detection": {"component": "packs.leaks", "detector": "duplicate_subscription",
                                   "subject": {"counterparty_id": payee}},
        })

    # Payment fees on wallet inflows.
    fee_refs = data.tags.get("wallet_fee", [])
    fee_rows = [r for r in data.statements["wallet"] if r.tag == "wallet_fee"]
    fees = -sum(r.amount_minor for r in fee_rows)
    out.append({
        "id": f"{pre}-LEAK-PAYMENT-FEES", "business_id": biz, "category": "leak", "kind": "payment_fees",
        "summary": f"{s.wallet_provider} merchant fees at {s.wallet_fee_rate * 100:.1f}% plus a monthly platform fee",
        # Total fees, not a leak amount: the pack reports only the excess over its healthy fee share, so tests
        # assert detection here, not the figure.
        "facts": {"fee_rate_pct": round(s.wallet_fee_rate * 100, 2), "total_fees_minor": fees,
                  "yearly_fees_minor": annualize(fees), "rows": len(fee_refs)},
        "evidence": {"file": "statements/wallet.csv", "references": fee_refs},
        "expected_detection": {"component": "packs.leaks", "detector": "payment_fees",
                               "assert": "detected; impact is the pack's excess over its healthy fee share"},
    })

    # Products sold at or below cost.
    for p in s.products:
        rows = [ln for ln in data.sale_lines if ln["product_id"] == p.id]
        rev, cost = sum(r["revenue_minor"] for r in rows), sum(r["cost_minor"] for r in rows)
        if rows and rev - cost < 0:
            out.append({
                "id": f"{pre}-LEAK-UNPROFITABLE-{p.id}", "business_id": biz, "category": "leak",
                "kind": "unprofitable_product", "summary": f"{p.name} is sold below supplier cost",
                "facts": {"product_id": p.id, "revenue_minor": rev, "cost_minor": cost,
                          "gross_profit_minor": rev - cost, "yearly_impact_minor": annualize(cost - rev)},
                "evidence": {"file": "sale_lines.csv", "filter": {"product_id": p.id}, "rows": len(rows)},
                "expected_detection": {"component": "packs.leaks", "detector": "unprofitable_products",
                                       "subject": {"product_id": p.id}},
            })

    # Missed early-pay discounts.
    missed = [i for i in data.invoices if i["discount_pct"] and i["paid_on"] and i["paid_on"] > i["discount_deadline"]]
    if missed:
        total = sum(int(round(i["total_minor"] * i["discount_pct"])) for i in missed)
        out.append({
            "id": f"{pre}-LEAK-MISSED-EARLY-PAY-DISCOUNT", "business_id": biz, "category": "leak",
            "kind": "missed_early_pay_discount",
            "summary": "Supplier offers a discount for paying within 10 days; invoices are paid near the due date",
            "facts": {"supplier_id": missed[0]["supplier_id"], "discount_pct": missed[0]["discount_pct"] * 100,
                      "invoices": len(missed), "total_missed_minor": total, "yearly_impact_minor": annualize(total)},
            "evidence": {"file": "purchases.csv", "invoice_ids": [i["id"] for i in missed]},
            "expected_detection": {"component": "packs.leaks", "detector": "missed_early_pay_discounts"},
        })

    # Late fees.
    for b in s.bills:
        refs = data.tags.get(f"late_fee:{b.id}")
        if refs:
            fee = sum(x[2] for x in b.late)
            out.append({
                "id": f"{pre}-LEAK-LATE-FEE-{b.id.removeprefix('bill_').upper()}", "business_id": biz,
                "category": "leak", "kind": "late_fee", "summary": f"Late payment fee charged by {b.payee}",
                "facts": {"counterparty_id": b.counterparty_id, "total_minor": fee,
                          "yearly_impact_minor": annualize(fee)},
                "evidence": {"file": "statements/bank.csv", "references": refs},
                "expected_detection": {"component": "packs.leaks", "detector": "late_fees"},
            })

    # Overdue customer dues, with the T2 reminder boundary each one exercises.
    cap = reminder_cap_minor()
    customers = {c.id: c for c in s.customers}
    for r in data.receivables:
        due = date.fromisoformat(r["due_date"])
        if r["status"] != "open" or due >= SIM_TODAY:
            continue
        c = customers[r["customer_id"]]
        if not c.allowlisted:
            t2 = {"eligible": False, "reason": "customer_not_allowlisted"}
        elif r["amount_minor"] > cap:
            t2 = {"eligible": False, "reason": "over_cap", "cap_minor": cap}
        else:
            t2 = {"eligible": True, "reason": "within_mandate", "cap_minor": cap}
        out.append({
            "id": f"{pre}-DUE-{r['id']}", "business_id": biz, "category": "receivable", "kind": "overdue_receivable",
            "summary": f"{c.name} invoice is overdue",
            "facts": {"invoice_id": r["id"], "customer_id": c.id, "amount_minor": r["amount_minor"],
                      "due_date": r["due_date"], "days_overdue": (SIM_TODAY - due).days,
                      "allowlisted": c.allowlisted},
            "evidence": {"file": "receivables.csv", "row_ids": [r["id"]]},
            "expected_detection": {"component": "engine.receivables", "detector": "overdue_receivables",
                                   "t2_send_invoice_reminder": t2},
        })

    # Slow-moving stock bought once and barely sold.
    for p in s.products:
        if p.reorder:
            continue
        bought = sum(ln["qty"] for ln in data.purchases if ln["product_id"] == p.id)
        sold = sum(ln["qty"] for ln in data.sale_lines if ln["product_id"] == p.id)
        first = min(ln["invoice_date"] for ln in data.purchases if ln["product_id"] == p.id)
        out.append({
            "id": f"{pre}-INV-SLOW-MOVER-{p.id}", "business_id": biz, "category": "inventory",
            "kind": "slow_moving_stock", "summary": f"{p.name}: most of a one-off buy is still unsold",
            "facts": {"product_id": p.id, "units_bought": bought, "units_sold": sold,
                      "units_on_hand": bought - sold, "stock_value_minor": (bought - sold) * p.cost_minor,
                      "first_purchase": first, "days_held": (SIM_TODAY - date.fromisoformat(first)).days},
            "evidence": {"file": "purchases.csv", "filter": {"product_id": p.id}},
            "expected_detection": {"component": "packs.leaks", "detector": "slow_moving_stock",
                                   "subject": {"product_id": p.id}},
        })

    # Holiday spikes inside the history window.
    daily = defaultdict(int)
    for ln in data.sale_lines:
        daily[ln["date"]] += ln["revenue_minor"]
    windows = {d.isoformat() for h in holidays for d in daterange(h.start, h.end)}
    for h in holidays:
        if h.end > HISTORY_END or h.start < HISTORY_START:
            continue
        in_window = [daily[d.isoformat()] for d in daterange(h.start, h.end)]
        base_days = [h.start - timedelta(days=k) for k in range(1, 29)]
        baseline = [daily[d.isoformat()] for d in base_days
                    if d >= HISTORY_START and d.isoformat() not in windows]
        ratio = (sum(in_window) / len(in_window)) / (sum(baseline) / len(baseline))
        out.append({
            "id": f"{pre}-SEASON-{h.key.upper()}", "business_id": biz, "category": "seasonality",
            "kind": "holiday_spike", "summary": f"Sales spike in the {h.name} shopping window",
            "facts": {"holiday_id": h.id, "holiday_key": h.key, "start": h.start.isoformat(),
                      "end": h.end.isoformat(), "configured_uplift": s.holiday_uplift[h.id],
                      "observed_ratio_vs_prior_4_weeks": round(ratio, 2)},
            "evidence": {"file": "sale_lines.csv", "filter": {"date_from": h.start.isoformat(),
                                                              "date_to": h.end.isoformat()}},
            "expected_detection": {"component": "engine.forecast", "detector": "seasonality",
                                   "holiday_calendar": "holidays.yaml"},
        })
    upcoming = [h for h in holidays if h.start >= SIM_TODAY]
    if upcoming:
        h = upcoming[0]
        out.append({
            "id": f"{pre}-SEASON-UPCOMING-{h.key.upper()}", "business_id": biz, "category": "seasonality",
            "kind": "upcoming_holiday", "summary": f"{h.name} window starts within the forecast horizon",
            "facts": {"holiday_id": h.id, "holiday_key": h.key, "start": h.start.isoformat(),
                      "end": h.end.isoformat(), "pack_uplift": s.holiday_uplift[h.id]},
            "evidence": {"file": "holidays.yaml", "key": h.key},
            "expected_detection": {"component": "engine.forecast", "detector": "seasonality"},
        })

    # Known upcoming payables the forecast must include (the next payroll and rent).
    for category in ("payroll", "rent"):
        item = next(i for i in data.scheduled_items if i["category"] == category)
        out.append({
            "id": f"{pre}-SCHEDULE-NEXT-{category.upper()}", "business_id": biz, "category": "schedule",
            "kind": "known_payable", "summary": f"Next {category} payment is scheduled",
            "facts": {"scheduled_item_id": item["id"], "due_date": item["due_date"],
                      "amount_minor": item["amount_minor"]},
            "evidence": {"file": "scheduled_items.csv", "row_ids": [item["id"]]},
            "expected_detection": {"component": "engine.forecast", "detector": "scheduled_items"},
        })
    return out
