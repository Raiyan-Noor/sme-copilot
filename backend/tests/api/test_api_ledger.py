"""Ledger transactions and statement upload: all-or-nothing, idempotent, PII tokenized, every upload logged."""

import asyncio
import sqlite3

from app.api.ledger import _transaction_events
from tests.api.conftest import MAYA

STATEMENT = (
    "date,description,amount,balance\n"
    "2026-10-18,TRANSFER FROM ACCT 5566778899 REF X,120.50,1120.50\n"
    "2026-10-18,CARD PURCHASE HARDWARE,-20.00,1100.50\n"
)
ACCOUNT_NUMBER = "9988 7766 5544"


def _upload(api, csv: str, account_number: str = ACCOUNT_NUMBER, **form):
    return api.post(f"/businesses/{MAYA}/statements", files={"file": ("new.csv", csv.encode(), "text/csv")},
                    data={"account_number": account_number, "account_name": "Second bank", **form})


def test_transactions_are_paged_newest_first_and_categorized(read_api):
    page = read_api.get(f"/businesses/{MAYA}/transactions", params={"limit": 5}).json()
    assert page["total"] > 1000 and len(page["items"]) == 5
    dates = [t["posted_on"] for t in page["items"]]
    assert dates == sorted(dates, reverse=True)
    assert all(t["category"] for t in page["items"])
    asc = read_api.get(f"/businesses/{MAYA}/transactions", params={"limit": 1, "order": "asc"}).json()
    assert asc["items"][0]["posted_on"] <= dates[-1]


def test_transaction_filters(read_api):
    rent = read_api.get(f"/businesses/{MAYA}/transactions", params={"category": "rent", "limit": 500}).json()
    assert rent["total"] >= 5 and {t["category"] for t in rent["items"]} == {"rent"}
    assert all(t["amount_minor"] < 0 for t in rent["items"])
    sept = read_api.get(f"/businesses/{MAYA}/transactions",
                        params={"date_from": "2026-09-01", "date_to": "2026-09-30", "limit": 500}).json()
    assert sept["total"] > 0 and all("2026-09-01" <= t["posted_on"] <= "2026-09-30" for t in sept["items"])
    assert read_api.get(f"/businesses/{MAYA}/transactions", params={"limit": 501}).status_code == 422


def test_upload_ingests_tokenizes_and_logs(api, data_dir):
    before = api.get(f"/businesses/{MAYA}").json()["transactions"]
    r = _upload(api, STATEMENT)
    assert r.status_code == 200, r.text
    report = r.json()
    assert (report["rows"], report["inserted"], report["duplicates"]) == (2, 2, 0)
    assert report["account_id"].startswith("acct_")
    assert api.get(f"/businesses/{MAYA}").json()["transactions"] == before + 2

    rows = api.get(f"/businesses/{MAYA}/transactions", params={"account_id": report["account_id"]}).json()
    assert rows["total"] == 2
    assert "5566778899" not in str(rows) and "acct_" in rows["items"][-1]["description"]

    logged = api.get("/audit", params={"kind": "ledger.statement_ingested"}).json()["entries"]
    assert logged[0]["data"]["import_id"] == report["import_id"]
    log_text = (data_dir / "audit.jsonl").read_text(encoding="utf-8")
    assert "9988" not in log_text and "5566778899" not in log_text


def test_reupload_adds_no_duplicates(api):
    assert _upload(api, STATEMENT).json()["inserted"] == 2
    again = _upload(api, STATEMENT).json()
    assert (again["inserted"], again["duplicates"]) == (0, 2)


def test_bad_statement_is_rejected_whole(api, data_dir):
    before = api.get(f"/businesses/{MAYA}").json()["transactions"]
    bad = STATEMENT + "2026-13-40,BAD DATE,1.00,\n2026-10-18,TOO PRECISE,1.005,\n"
    r = _upload(api, bad)
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert [e["line"] for e in errors] == [4, 5]
    assert api.get(f"/businesses/{MAYA}").json()["transactions"] == before
    conn = sqlite3.connect(data_dir / f"{MAYA}.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM pii_vault WHERE value LIKE '%5566778899%'").fetchone()[0] == 0
    conn.close()
    assert api.get("/audit", params={"kind": "ledger.statement_rejected"}).json()["total"] == 1


def test_upload_limits(api):
    assert _upload(api, STATEMENT, decimal_sep=";").status_code == 422
    assert _upload(api, STATEMENT, account_number="").status_code == 422
    huge = "date,description,amount\n" + "2026-10-18,X,1.00\n" * 400_000
    assert _upload(api, huge).status_code == 413


def test_transaction_rows_carry_running_balance_source_and_status(read_api):
    asc = read_api.get(f"/businesses/{MAYA}/transactions", params={"order": "asc", "limit": 500}).json()["items"]
    running = 0
    for row in asc:
        running += row["amount_minor"]
        assert row["running_balance_minor"] == running
        assert row["source"] == "import"
        assert row["status"] == "settled"


def test_transaction_search_and_direction_filters(read_api):
    rent = read_api.get(f"/businesses/{MAYA}/transactions", params={"search": "rent", "limit": 500}).json()
    assert rent["total"] > 0
    assert all("rent" in (t["description"] + (t["counterparty"] or "")).lower() for t in rent["items"])

    money_in = read_api.get(f"/businesses/{MAYA}/transactions", params={"direction": "in", "limit": 500}).json()
    assert money_in["total"] > 0 and all(t["amount_minor"] >= 0 for t in money_in["items"])
    money_out = read_api.get(f"/businesses/{MAYA}/transactions", params={"direction": "out", "limit": 500}).json()
    assert money_out["total"] > 0 and all(t["amount_minor"] < 0 for t in money_out["items"])
    everything = read_api.get(f"/businesses/{MAYA}/transactions", params={"limit": 500}).json()
    assert money_in["total"] + money_out["total"] == everything["total"]


def test_get_one_transaction_and_404(read_api):
    first = read_api.get(f"/businesses/{MAYA}/transactions", params={"limit": 1}).json()["items"][0]
    row = read_api.get(f"/businesses/{MAYA}/transactions/{first['id']}").json()
    assert row["id"] == first["id"] and row["running_balance_minor"] == first["running_balance_minor"]
    assert read_api.get(f"/businesses/{MAYA}/transactions/no-such-row").status_code == 404


def test_transactions_csv_export_matches_filtered_view(read_api):
    page = read_api.get(f"/businesses/{MAYA}/transactions",
                        params={"category": "rent", "order": "asc", "limit": 500}).json()
    r = read_api.get(f"/businesses/{MAYA}/transactions/export", params={"category": "rent", "order": "asc"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert len(lines) - 1 == len(page["items"])  # header + one row per transaction
    assert lines[0].split(",")[0] == "posted_on"


class _FakeRequest:
    """A test client buffers a StreamingResponse to completion before returning it, which can never happen for an
    endpoint that polls forever. Drive the generator directly instead, with a stand-in for FastAPI's `Request`."""

    async def is_disconnected(self) -> bool:
        return False


def test_transactions_stream_sends_a_new_row_on_upload(api):
    rt = api.app.state.runtime

    async def run() -> list[str]:
        frames: list[str] = []

        async def consume() -> None:
            async for frame in _transaction_events(rt, MAYA, _FakeRequest(), poll_seconds=0.05):
                frames.append(frame)
                if frame.startswith("event: balance"):  # always the last frame of a batch
                    return

        async def upload_soon() -> None:
            await asyncio.sleep(0.1)
            await asyncio.to_thread(_upload, api, STATEMENT)

        await asyncio.wait_for(asyncio.gather(consume(), upload_soon()), timeout=5)
        return frames

    frames = asyncio.run(run())
    assert any(f.startswith("event: transaction") for f in frames)
    assert any(f.startswith("event: balance") for f in frames)
