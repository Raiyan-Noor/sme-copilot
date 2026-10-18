"""Shared fixtures. Tests always run in LLM replay mode with no API keys and never read the developer's .env."""

import os

os.environ["LLM_REPLAY"] = "replay"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from tests.helpers import make_settings  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(make_settings()))


class Attack:
    """What one red-team test reports to `make redteam` (scripts/redteam.py): which attack it tries and which
    defenses stopped it. Defenses are recorded from what the run returned (the gateway's rule, the flags raised),
    never written down in advance; whether the attack was blocked is the test's own pass/fail."""

    def __init__(self, record):
        self.data: dict = {"attack_id": None, "variant": None, "driver": None, "defenses": []}
        record("redteam", self.data)

    def __call__(self, attack_id: str, variant: str, driver: str) -> "Attack":
        """`driver`: who plays the attacker. `scripted` = a hijacked planner (FakeLLM) or a direct API caller;
        `live_llm` = a real model in the loop (the planner, or the quarantined extractor reading planted mail),
        recorded once per provider and replayed."""
        self.data.update(attack_id=attack_id, variant=variant, driver=driver)
        return self

    def caught(self, layer: str, rule: str | None) -> None:
        entry = {"layer": layer, "rule": rule}
        if entry not in self.data["defenses"]:
            self.data["defenses"].append(entry)


class Task:
    """What one benign test reports: the owner task and what the agent did (statuses, facts cited)."""

    def __init__(self, record):
        self.data: dict = {"task_id": None, "business": None, "kind": None, "outcome": {}}
        record("benign", self.data)

    def __call__(self, task_id: str, business: str, kind: str) -> "Task":
        self.data.update(task_id=task_id, business=business, kind=kind)
        return self


@pytest.fixture
def attack(record_property) -> Attack:
    return Attack(record_property)


@pytest.fixture
def task(record_property) -> Task:
    return Task(record_property)


# --- `make redteam` collection: only active when scripts/redteam.py sets REDTEAM_REPORT --------------------------

_REPORT: dict[str, dict] = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not os.environ.get("REDTEAM_REPORT"):
        return
    rep = outcome.get_result()
    props = dict(item.user_properties)
    if "redteam" not in props and "benign" not in props:
        return
    entry = _REPORT.setdefault(item.nodeid, {"nodeid": item.nodeid, "outcome": "passed", **props})
    if rep.failed:
        entry["outcome"] = "failed"
        entry["failure"] = (rep.longreprtext or "").strip().splitlines()[-1:]  # the last line: what broke
    elif rep.skipped and entry["outcome"] == "passed":
        entry["outcome"] = "skipped"


def pytest_sessionfinish(session):
    path = os.environ.get("REDTEAM_REPORT")
    if path:
        import json
        from pathlib import Path

        Path(path).write_text(json.dumps(list(_REPORT.values()), indent=1, default=str), encoding="utf-8")
