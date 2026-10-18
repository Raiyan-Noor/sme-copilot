"""Policy-suite fixtures; helpers live in tests/gateway_env.py so test modules can import them."""

from pathlib import Path

import pytest

from tests.gateway_env import Env


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)
