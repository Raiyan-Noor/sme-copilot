"""API test fixtures: seed data generated once per session, loaded once into a template data dir through the real
bootstrap, then copied per test so each test gets an isolated tenant set, clock and audit log."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import PASSCODE_HEADER, create_app
from tests.helpers import TEST_PASSCODE, make_settings

MAYA = "maya-corner-store"
LINA = "lina-boutique"


@pytest.fixture(scope="session")
def seed_dir(tmp_path_factory) -> Path:
    from data.seed.generate import generate

    out = tmp_path_factory.mktemp("generated")
    generate(out)
    return out


@pytest.fixture(scope="session")
def template_data_dir(seed_dir, tmp_path_factory) -> Path:
    data_dir = tmp_path_factory.mktemp("template") / "tenants"
    app = create_app(make_settings(data_dir=data_dir, seed_dir=seed_dir))
    app.state.runtime.ensure_ready()
    return data_dir


def api_client(data_dir: Path, seed_dir: Path, **overrides) -> TestClient:
    app = create_app(make_settings(data_dir=data_dir, seed_dir=seed_dir, **overrides))
    return TestClient(app, headers={PASSCODE_HEADER: TEST_PASSCODE})


@pytest.fixture
def data_dir(template_data_dir, tmp_path) -> Path:
    dest = tmp_path / "tenants"
    shutil.copytree(template_data_dir, dest)
    return dest


@pytest.fixture
def api(data_dir, seed_dir) -> TestClient:
    """A fresh, isolated app (copied tenants) with the passcode header set."""
    return api_client(data_dir, seed_dir)


@pytest.fixture(scope="module")
def read_api(template_data_dir, seed_dir, tmp_path_factory) -> TestClient:
    """One app per module for read-only tests, so facts are computed once."""
    dest = tmp_path_factory.mktemp("read") / "tenants"
    shutil.copytree(template_data_dir, dest)
    return api_client(dest, seed_dir)
