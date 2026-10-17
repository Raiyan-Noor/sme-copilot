"""Test helpers: settings that never read the developer's .env and always use LLM replay mode."""

from app.config import Settings

TEST_PASSCODE = "test-passcode"
TEST_ORIGIN = "http://localhost:3000"


def make_settings(**overrides) -> Settings:
    values = {"demo_passcode": TEST_PASSCODE, "allowed_origins": TEST_ORIGIN, "llm_replay": "replay"}
    values.update(overrides)
    return Settings(_env_file=None, **values)
