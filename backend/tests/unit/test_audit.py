"""Hash-chained audit log (invariant 7): append, head, verify, export, tamper detection, canonical JSON."""

import json
from datetime import date

import pytest

import app.audit as audit
from app.audit import GENESIS_HASH, AuditLog, canonical_hash, canonical_json
from app.audit.canonical import CanonicalError
from app.clock import SimClock


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl", SimClock(date(2026, 10, 18)))


def _fill(log, n=5):
    return [log.append("test.event", {"i": i, "note": f"entry {i}"}) for i in range(n)]


def _rewrite(log, lines):
    log.path.write_text("".join(lines), encoding="utf-8")


def test_empty_log_head_is_genesis(log):
    assert log.head().seq == -1 and log.head().hash == GENESIS_HASH
    assert log.verify().ok and log.verify().entries == 0


def test_entries_chain_and_head_tracks_last(log):
    entries = _fill(log)
    assert entries[0].prev_hash == GENESIS_HASH
    for prev, cur in zip(entries, entries[1:]):
        assert cur.prev_hash == prev.hash and cur.seq == prev.seq + 1
    assert log.head().hash == entries[-1].hash and log.head().seq == 4
    result = log.verify()
    assert result.ok and result.entries == 5 and result.head == log.head()


def test_entry_hash_is_canonical_hash_of_body(log):
    e = log.append("x", {"b": 1, "a": "é"})
    assert e.hash == canonical_hash(e.body())
    assert e.date == "2026-10-18"


def test_reopen_continues_chain(log):
    _fill(log, 3)
    reopened = AuditLog(log.path, log.clock)
    assert reopened.head() == log.head()
    e = reopened.append("after.restart")
    assert e.seq == 3 and reopened.verify().ok


@pytest.mark.parametrize("mutate, bad_seq", [
    (lambda lines: lines.__setitem__(2, lines[2].replace("entry 2", "entry X")), 2),  # edit data
    (lambda lines: lines.pop(2), 2),                                                   # delete
    (lambda lines: lines.insert(1, lines[3]), 1),                                      # duplicate/insert
    (lambda lines: lines.__setitem__(1, lines[1][:-5] + "\n"), 1),                     # truncate a line
])
def test_tampering_is_detected(log, mutate, bad_seq):
    _fill(log)
    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    mutate(lines)
    _rewrite(log, lines)
    result = log.verify()
    assert not result.ok and result.first_bad_seq == bad_seq


def test_swapping_two_entries_detected(log):
    _fill(log)
    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1], lines[3] = lines[3], lines[1]
    _rewrite(log, lines)
    assert not log.verify().ok


def test_edit_with_recomputed_entry_hash_still_breaks_next_link(log):
    _fill(log)
    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    entry = json.loads(lines[2])
    entry["data"]["note"] = "rewritten"
    entry["hash"] = canonical_hash({k: v for k, v in entry.items() if k != "hash"})
    lines[2] = json.dumps(entry) + "\n"
    _rewrite(log, lines)
    result = log.verify()
    assert not result.ok and result.first_bad_seq == 3


def test_added_field_detected(log):
    _fill(log, 2)
    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    entry = json.loads(lines[1])
    entry["extra"] = "smuggled"
    lines[1] = json.dumps(entry) + "\n"
    _rewrite(log, lines)
    assert not log.verify().ok


def test_export_copies_and_verifies(log, tmp_path):
    _fill(log)
    result = log.export(tmp_path / "out" / "audit_export.jsonl")
    assert result.ok and result.head == log.head()
    assert (tmp_path / "out" / "audit_export.jsonl").read_bytes() == log.path.read_bytes()


def test_subscribers_see_every_append(log):
    seen = []
    log.subscribe(seen.append)
    entries = _fill(log, 3)
    assert seen == entries


def test_module_level_append_uses_configured_log(log, monkeypatch):
    monkeypatch.setattr(audit, "_default", None)
    with pytest.raises(RuntimeError):
        audit.append("x")
    audit.configure(log)
    e = audit.append("module.event", {"ok": True})
    assert audit.head().hash == e.hash


def test_canonical_json_is_sorted_compact_utf8():
    assert canonical_json({"b": 1, "a": ["é", None, True]}) == '{"a":["é",null,true],"b":1}'.encode()


@pytest.mark.parametrize("bad", [{"x": 1.5}, [float("nan")], {1: "int key"}])
def test_canonical_json_rejects_floats_and_non_string_keys(bad):
    with pytest.raises(CanonicalError):
        canonical_json(bad)
