"""Six months of transactions for one business, plus its forward schedule and planted anomalies.

Pure function of (spec, holiday calendar, numpy Generator, Faker): no wall clock, no set iteration, no unseeded
randomness. Statements are written in the column names prompt 2's ingester accepts; `reference` is unique per row
and is how the manifest points at evidence rows.
"""

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from faker import Faker

from data.seed.businesses import (
    HISTORY_END,
    HISTORY_START,
    SCHEDULE_HORIZON_DAYS,
    SIM_TODAY,
    Bill,
    BusinessSpec,
    Product,
    Supplier,
)

DAY = timedelta(days=1)
# Moves between the business's own accounts (wallet settlement, cash banked). Revenue is counted where it arises
# (wallet payments, cash Z-reports); these rows must be treated as transfers or revenue is counted twice.
INTERNAL = "internal_transfer"
CUSTOMER_INVOICE = "customer_invoice"  # pack revenue category for credit-customer payments


@dataclass(frozen=True)
class Holiday:
    id: str
    key: str
    name: str
    start: date
    end: date
    holiday_date: date


@dataclass
class Row:
    """One statement line before references and running balances are assigned."""

    date: date
    order: int  # intra-day ordering
    description: str
    amount_minor: int
    counterparty: str = ""
    counterparty_account: str = ""
    counterparty_phone: str = ""
    channel: str = ""
    tag: str = ""  # internal: lets the manifest find this row's reference
    reference: str = ""
    balance_minor: int = 0


@dataclass
class BusinessData:
    spec: BusinessSpec
    staff: list[dict]
    statements: dict[str, list[Row]]  # account id -> rows
    sale_lines: list[dict]
    purchases: list[dict]  # invoice lines
    invoices: list[dict]  # supplier invoice headers (for the mailbox)
    receivables: list[dict]
    scheduled_items: list[dict]
    anomalies: list[dict]
    address: str
    tags: dict[str, list[str]] = field(default_factory=dict)  # tag -> references


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += DAY


def months_between(a: date, b: date) -> float:
    return (b - a).days / 30.44


def money(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d}"


class Calendar:
    def __init__(self, holidays: list[Holiday]):
        self.holidays = holidays
        self.closed = {h.holiday_date for h in holidays}

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.closed

    def next_business_day(self, d: date) -> date:
        while not self.is_business_day(d):
            d += DAY
        return d

    def prev_business_day(self, d: date) -> date:
        while not self.is_business_day(d):
            d -= DAY
        return d

    def holiday_id(self, d: date) -> str | None:
        for h in self.holidays:
            if h.start <= d <= h.end:
                return h.id
        return None


def month_day(year: int, month: int, day: int) -> date:
    """Day `day` of the month, clamped to the month's last day."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


class Generator:
    def __init__(self, spec: BusinessSpec, holidays: list[Holiday], rng: np.random.Generator, fake: Faker):
        self.s = spec
        self.cal = Calendar(holidays)
        self.rng = rng
        self.fake = fake
        self.products = {p.id: p for p in spec.products}
        self.suppliers = {s.id: s for s in spec.suppliers}
        self.bank: list[Row] = []
        self.wallet: list[Row] = []
        self.cash: list[Row] = []
        self.anomalies: list[dict] = []

    # ---- demand ---------------------------------------------------------------------------------------------

    def expected_units(self, p: Product, d: date) -> float:
        f = p.base_units * self.s.weekday_factors[d.weekday()]
        f *= dict(p.month_factors).get(d.month, 1.0)
        hid = self.cal.holiday_id(d)
        if hid:
            f *= 1 + (self.s.holiday_uplift[hid] - 1) * p.holiday_sensitivity
        return f

    def unit_cost(self, p: Product, d: date) -> int:
        return int(round(p.cost_minor * (1 + p.cost_creep_monthly) ** months_between(HISTORY_START, d)))

    # ---- main -----------------------------------------------------------------------------------------------

    def run(self) -> BusinessData:
        staff = self.make_staff()
        sale_lines = self.sales_and_payments()
        purchases, invoices = self.purchasing()
        self.bills_payroll_draws(staff)
        receivables = self.receivables()
        statements = {"bank": self.bank, "wallet": self.wallet, "cash": self.cash}
        opening = {"bank": self.s.opening_bank_minor, "wallet": 0, "cash": self.s.opening_cash_minor}
        tags: dict[str, list[str]] = {}
        codes = {"bank": "BNK", "wallet": "WAL", "cash": "CSH"}
        for acct, rows in statements.items():
            rows.sort(key=lambda r: (r.date, r.order))
            bal = opening[acct]
            for n, r in enumerate(rows, start=1):
                bal += r.amount_minor
                r.balance_minor = bal
                r.reference = f"{self.s.ref_prefix}-{codes[acct]}-{n:06d}"
                if r.tag:
                    tags.setdefault(r.tag, []).append(r.reference)
        self.resolve_payment_refs(purchases, receivables, tags)
        scheduled = self.scheduled_items(staff, invoices, receivables)
        data = BusinessData(
            spec=self.s, staff=staff, statements=statements, sale_lines=sale_lines, purchases=purchases,
            invoices=invoices, receivables=receivables, scheduled_items=scheduled, anomalies=[],
            address=self.fake.street_address() + ", " + self.fake.city(), tags=tags,
        )
        return data

    def make_staff(self) -> list[dict]:
        staff = []
        for i, net in enumerate(self.s.staff_net_monthly_minor, start=1):
            first, last = self.fake.first_name(), self.fake.last_name()
            staff.append({
                "id": f"stf_{i:02d}", "name": f"{first} {last}", "first_name": first,
                "email": f"{first.lower()}@{self.s.domain}",
                "national_id": f"{self.rng.integers(100, 999)}-{self.rng.integers(10, 99)}-"
                               f"{self.rng.integers(1000, 9999)}",
                "bank_account": f"{self.rng.integers(1000, 9999)} {self.rng.integers(1000, 9999)} "
                                f"{self.rng.integers(1000, 9999)}",
                "net_monthly_minor": net,
            })
        return staff

    # ---- sales, wallet, cash ----------------------------------------------------------------------------------

    def sales_and_payments(self) -> list[dict]:
        s, rng = self.s, self.rng
        phones = [f"+999 7{rng.integers(10, 99)} {rng.integers(100, 999)} {rng.integers(1000, 9999)}"
                  for _ in range(s.payer_pool)]
        weights = 1.0 / np.arange(1, s.payer_pool + 1) ** 0.6
        weights = weights / weights.sum()
        # Returns follow what actually sells (revenue share), so a slow mover is rarely returned.
        refund_w = np.array([p.price_minor * p.base_units for p in s.products], dtype=float)
        refund_w = refund_w / refund_w.sum()
        sale_lines: list[dict] = []
        wallet_bal = 0
        cash_bal = s.opening_cash_minor
        line_no = 0
        for d in daterange(HISTORY_START, HISTORY_END):
            # Morning: settle the wallet's previous closing balance to the bank on business days.
            if self.cal.is_business_day(d) and wallet_bal > 0 and d > HISTORY_START:
                self.wallet.append(Row(d, 0, f"SETTLEMENT TO BANK ACCT {s.bank_account_number}", -wallet_bal,
                                       s.bank_name, s.bank_account_number, channel=INTERNAL))
                self.bank.append(Row(d, 10, f"PAYNEST SETTLEMENT MERCHANT {s.wallet_account_number}", wallet_bal,
                                     s.wallet_provider, s.wallet_account_number, channel=INTERNAL,
                                     tag="wallet_settlement"))
                wallet_bal = 0
            if d.day == 1:
                self.wallet.append(Row(d, 1, "MONTHLY MERCHANT FEE PLATFORM", -s.wallet_monthly_fee_minor,
                                       s.wallet_provider, channel="fee", tag="wallet_fee"))
                wallet_bal -= s.wallet_monthly_fee_minor
            # Monday morning: bank the cash above the float.
            if d.weekday() == 0 and self.cal.is_business_day(d) and cash_bal > s.cash_float_minor:
                dep = cash_bal - s.cash_float_minor
                self.cash.append(Row(d, 0, "CASH DEPOSIT TO BANK", -dep, s.bank_name, s.bank_account_number,
                                     channel=INTERNAL))
                self.bank.append(Row(d, 11, "CASH DEPOSIT BRANCH", dep, s.name, channel=INTERNAL,
                                     tag="cash_deposit"))
                cash_bal -= dep

            noise = math.exp(rng.normal(0, s.day_noise_sd))
            day_total = 0
            for p in s.products:
                qty = int(rng.poisson(self.expected_units(p, d) * noise))
                if qty <= 0:
                    continue
                line_no += 1
                rev = qty * p.price_minor
                day_total += rev
                sale_lines.append({"id": f"{s.ref_prefix}-SL-{line_no:06d}", "date": d.isoformat(),
                                   "product_id": p.id, "qty": qty, "unit_price_minor": p.price_minor,
                                   "revenue_minor": rev, "cost_minor": qty * self.unit_cost(p, d)})
            # Wallet tickets for part of the day's sales; the rest is cash.
            share = float(np.clip(rng.normal(s.wallet_share, 0.04), 0.2, 0.85))
            wallet_total = int(round(day_total * share))
            n = max(1, int(round(wallet_total / s.ticket_mean_minor)))
            w = rng.gamma(2.0, 1.0, size=n)
            amounts = np.floor(w / w.sum() * wallet_total).astype(int)
            amounts = np.maximum(amounts, 1)
            amounts[int(np.argmax(amounts))] += wallet_total - int(amounts.sum())
            payers = rng.choice(s.payer_pool, size=n, p=weights)
            for k, (amt, payer) in enumerate(zip(amounts.tolist(), payers.tolist(), strict=True)):
                self.wallet.append(Row(d, 10 + k, "PAYMENT RECEIVED", amt, "Wallet customer",
                                       counterparty_phone=phones[payer], channel="wallet", tag="wallet_payment"))
            wallet_bal += wallet_total
            # Refunds go back through the wallet (fashion returns).
            if s.refund_daily_prob and rng.random() < s.refund_daily_prob:
                p = s.products[int(rng.choice(len(s.products), p=refund_w))]
                line_no += 1
                sale_lines.append({"id": f"{s.ref_prefix}-SL-{line_no:06d}", "date": d.isoformat(),
                                   "product_id": p.id, "qty": -1, "unit_price_minor": p.price_minor,
                                   "revenue_minor": -p.price_minor, "cost_minor": -self.unit_cost(p, d)})
                self.wallet.append(Row(d, 9000, f"REFUND {p.name.upper()}", -p.price_minor, "Wallet customer",
                                       counterparty_phone=phones[int(rng.choice(s.payer_pool, p=weights))],
                                       channel="refund", tag="wallet_refund"))
                wallet_bal -= p.price_minor
            fee = int(round(wallet_total * s.wallet_fee_rate))
            self.wallet.append(Row(d, 9500, f"MERCHANT FEE MDR {s.wallet_fee_rate * 100:.1f}%", -fee,
                                   s.wallet_provider, channel="fee", tag="wallet_fee"))
            wallet_bal -= fee
            cash_total = day_total - wallet_total
            self.cash.append(Row(d, 9000, "CASH SALES Z-REPORT", cash_total, s.name, channel="cash_sale"))
            cash_bal += cash_total
            if rng.random() < s.petty_cash_daily_prob:
                label, lo, hi = s.petty_cash[int(rng.integers(len(s.petty_cash)))]
                amt = int(rng.integers(lo, hi + 1))
                self.cash.append(Row(d, 9100, f"PETTY CASH {label}", -amt, channel="petty_cash"))
                cash_bal -= amt
        return sale_lines

    # ---- suppliers ------------------------------------------------------------------------------------------

    def order_dates(self, sup: Supplier) -> list[date]:
        out = []
        for d in daterange(HISTORY_START, HISTORY_END):
            if (sup.order_weekdays and d.weekday() in sup.order_weekdays) or \
                    (sup.order_month_days and d.day in sup.order_month_days):
                out.append(d)
        return out

    def purchasing(self) -> tuple[list[dict], list[dict]]:
        rng = self.rng
        lines: list[dict] = []
        invoices: list[dict] = []
        for sup in self.s.suppliers:
            prods = [p for p in self.s.products if p.supplier_id == sup.id]
            regular = self.order_dates(sup)
            dates = list(regular)
            fixed = {}
            for fd, pid, qty in sup.fixed_orders:
                fixed.setdefault(fd, []).append((pid, qty))
                if fd not in dates:
                    dates.append(fd)
            dates.sort()
            seq = 0
            for i, d in enumerate(dates):
                nd = dates[i + 1] if i + 1 < len(dates) else d + timedelta(days=(7 if sup.order_weekdays else 14))
                if d in fixed and d not in regular:
                    nd = d  # one-off order only
                inv_lines = []
                for p in prods:
                    if not p.reorder:
                        continue
                    exp = sum(self.expected_units(p, x) for x in
                              daterange(d + timedelta(days=sup.lead_days), nd + timedelta(days=sup.lead_days - 1)))
                    qty = int(math.ceil(exp * math.exp(rng.normal(0.03, 0.06))))
                    if qty > 0:
                        inv_lines.append((p, qty))
                for pid, qty in fixed.get(d, []):
                    inv_lines.append((self.products[pid], qty))
                if not inv_lines:
                    continue
                seq += 1
                inv_id = f"{sup.invoice_prefix}-26-{seq:04d}"
                due = d + timedelta(days=sup.terms_days)
                lag = int(rng.integers(sup.pay_lag_days[0], sup.pay_lag_days[1] + 1))
                paid = self.cal.next_business_day(d + timedelta(days=lag))
                total = 0
                for k, (p, qty) in enumerate(inv_lines, start=1):
                    uc = self.unit_cost(p, d)
                    total += qty * uc
                    lines.append({
                        "id": f"{inv_id}-L{k:02d}", "invoice_id": inv_id, "supplier_id": sup.id,
                        "invoice_date": d.isoformat(), "due_date": due.isoformat(), "product_id": p.id,
                        "qty": qty, "unit_cost_minor": uc, "line_total_minor": qty * uc,
                    })
                discount_deadline = d + timedelta(days=sup.early_pay_days) if sup.early_pay_discount_pct else None
                inv = {"id": inv_id, "supplier_id": sup.id, "invoice_date": d, "due_date": due,
                       "total_minor": total, "paid_on": paid if paid <= HISTORY_END else None,
                       "discount_pct": sup.early_pay_discount_pct, "discount_deadline": discount_deadline,
                       "lines": inv_lines}
                invoices.append(inv)
                if inv["paid_on"]:
                    self.bank.append(Row(paid, 200, f"ACH PAYMENT {sup.name.upper()} INV {inv_id}", -total,
                                         sup.name, sup.account_number, channel="transfer", tag=f"inv:{inv_id}"))
        for ln in lines:
            inv = next(i for i in invoices if i["id"] == ln["invoice_id"])
            ln["paid_on"] = inv["paid_on"].isoformat() if inv["paid_on"] else ""
            ln["payment_reference"] = ""  # filled once references exist
            ln["early_pay_discount_pct"] = inv["discount_pct"]
            ln["discount_deadline"] = inv["discount_deadline"].isoformat() if inv["discount_deadline"] else ""
        return lines, invoices

    # ---- bills, payroll, owner draws ----------------------------------------------------------------------------

    def bill_amount(self, b: Bill, month: int) -> int:
        amt = b.amount_minor * dict(b.month_factors).get(month, 1.0)
        if b.sd_minor:
            amt += self.rng.normal(0, b.sd_minor)
        return int(round(amt))

    def bills_payroll_draws(self, staff: list[dict]) -> None:
        s = self.s
        for y, m in months(HISTORY_START, HISTORY_END):
            for b in s.bills:
                due = month_day(y, m, b.day)
                if due < HISTORY_START or due > HISTORY_END or (b.start and due < b.start):
                    continue
                late = {mm: (days, fee) for mm, days, fee in b.late}
                amt = self.bill_amount(b, m)
                days_late, fee = late.get(m, (0, 0))
                pay = self.cal.next_business_day(due + timedelta(days=days_late))
                if pay > HISTORY_END:
                    continue
                self.bank.append(Row(pay, 100, b.description, -amt, b.payee, b.account_number,
                                     channel="direct_debit", tag=f"bill:{b.id}"))
                if fee:
                    self.bank.append(Row(pay, 101, f"{b.payee.upper()} LATE PAYMENT FEE", -fee, b.payee,
                                         b.account_number, channel="direct_debit", tag=f"late_fee:{b.id}"))
            pay_day = self.cal.prev_business_day(month_day(y, m, s.payroll_day))
            if HISTORY_START <= pay_day <= HISTORY_END:
                for st in staff:
                    self.bank.append(Row(pay_day, 300, f"PAYROLL {st['name'].upper()}", -st["net_monthly_minor"],
                                         st["name"], st["bank_account"], channel="transfer", tag="payroll"))
            draw_day = self.cal.prev_business_day(month_day(y, m, s.owner_draw_day))
            if HISTORY_START <= draw_day <= HISTORY_END:
                self.bank.append(Row(draw_day, 400, "OWNER DRAWINGS TRANSFER TO SAVINGS", -s.owner_draw_minor,
                                     s.owner_name, channel="transfer", tag="owner_draw"))

    # ---- receivables ----------------------------------------------------------------------------------------

    def receivables(self) -> list[dict]:
        out = []
        for c in self.s.customers:
            unpaid = dict(c.unpaid)
            seq = 0
            for y, m in months(c.first_issue, HISTORY_END):
                issue = month_day(y, m, c.issue_day)
                if issue < c.first_issue or issue > HISTORY_END:
                    continue
                seq += 1
                inv_id = f"{self.s.ref_prefix}-AR-{c.id.removeprefix('cus_').upper()}-{seq:03d}"
                due = issue + timedelta(days=c.terms_days)
                if issue in unpaid:
                    amt = unpaid[issue]
                else:
                    amt = int(round(c.amount_mean_minor + self.rng.normal(0, c.amount_sd_minor) if c.amount_sd_minor
                                    else c.amount_mean_minor))
                rec = {"id": inv_id, "customer_id": c.id, "issue_date": issue.isoformat(),
                       "due_date": due.isoformat(), "amount_minor": amt, "status": "open", "paid_on": "",
                       "payment_reference": ""}
                delay = int(self.rng.integers(c.pay_delay_days[0], c.pay_delay_days[1] + 1))
                if issue not in unpaid and due < SIM_TODAY:
                    paid = self.cal.next_business_day(due + timedelta(days=delay))
                    if paid > HISTORY_END:
                        paid = self.cal.prev_business_day(HISTORY_END)
                    rec["status"], rec["paid_on"] = "paid", paid.isoformat()
                    self.bank.append(Row(paid, 20, f"TRANSFER FROM {c.name.upper()} REF {inv_id}", amt, c.name,
                                         channel="transfer", tag=f"ar:{inv_id}"))
                out.append(rec)
        return out

    def resolve_payment_refs(self, purchases, receivables, tags) -> None:
        for ln in purchases:
            refs = tags.get(f"inv:{ln['invoice_id']}")
            ln["payment_reference"] = refs[0] if refs else ""
        for r in receivables:
            refs = tags.get(f"ar:{r['id']}")
            r["payment_reference"] = refs[0] if refs else ""

    # ---- forward schedule ---------------------------------------------------------------------------------------

    def scheduled_items(self, staff, invoices, receivables) -> list[dict]:
        s = self.s
        horizon = SIM_TODAY + timedelta(days=SCHEDULE_HORIZON_DAYS)
        items: list[dict] = []

        def add(kind, category, due, amount, cp, source, ref):
            items.append({"kind": kind, "category": category, "due_date": due.isoformat(), "amount_minor": amount,
                          "status": "open", "counterparty_id": cp, "source": source, "reference": ref})

        for y, m in months(SIM_TODAY, horizon):
            for b in s.bills:
                due = self.cal.next_business_day(month_day(y, m, b.day))
                if SIM_TODAY <= due <= horizon:
                    amt = int(round(b.amount_minor * dict(b.month_factors).get(m, 1.0)))
                    add("payable", b.category, due, amt, b.counterparty_id,
                        "estimate" if b.sd_minor else "contract", b.id)
            pay_day = self.cal.prev_business_day(month_day(y, m, s.payroll_day))
            if SIM_TODAY <= pay_day <= horizon:
                add("payable", "payroll", pay_day, sum(st["net_monthly_minor"] for st in staff), "staff",
                    "contract", f"payroll-{y}-{m:02d}")
        for inv in invoices:
            if inv["paid_on"] is None:
                category = self.suppliers[inv["supplier_id"]].pack_category
                add("payable", category, inv["due_date"], inv["total_minor"], inv["supplier_id"],
                    "invoice", inv["id"])
        for r in receivables:
            if r["status"] == "open":
                add("receivable", CUSTOMER_INVOICE, date.fromisoformat(r["due_date"]), r["amount_minor"],
                    r["customer_id"], "invoice", r["id"])
        items.sort(key=lambda i: (i["due_date"], i["kind"], i["reference"]))
        for n, it in enumerate(items, start=1):
            it["id"] = f"{s.ref_prefix}-SCH-{n:04d}"
        return [{"id": it.pop("id"), **it} for it in items]


def generate_business(spec: BusinessSpec, holidays: list[Holiday], rng: np.random.Generator,
                      fake: Faker) -> BusinessData:
    return Generator(spec, holidays, rng, fake).run()
