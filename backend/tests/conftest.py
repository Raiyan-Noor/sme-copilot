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
