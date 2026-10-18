"""Runtime settings, read from the environment and the repo-root .env (gitignored).

Secrets (API keys, ANCHOR_PRIVATE_KEY) are SecretStr so they never appear in reprs or logs. The anchor chain ID is
checked against the testnet allow-list at load time (invariant 9): a mainnet chain ID makes the app refuse to start.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Invariant 9: anchoring is testnet-only. Sepolia and Base Sepolia.
ANCHOR_CHAIN_ALLOWLIST: frozenset[int] = frozenset({11155111, 84532})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Auth and CORS
    demo_passcode: SecretStr = SecretStr("")
    allowed_origins: str = "http://localhost:3000"

    # Data
    data_dir: Path = REPO_ROOT / "backend" / "data" / "tenants"
    # `make seed` output; businesses found here are loaded into data_dir on first use (synthetic data only).
    seed_dir: Path = REPO_ROOT / "backend" / "data" / "generated"
    holiday_calendar: Path = REPO_ROOT / "backend" / "data" / "seed" / "holidays.yaml"
    # Simulated clock start; defaults to the seed businesses' sim_today. Fast-forward state persists in data_dir.
    sim_start: date | None = None
    # Testing routes in /docs (e.g. propose an action directly, without the planner). Still fully gated.
    expose_test_routes: bool = True

    # LLM
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    llm_profile: Literal["dev", "demo"] = "dev"
    llm_replay: Literal["record", "replay", "off"] = "replay"
    llm_budget_usd: float = Field(default=7.0, ge=0)

    # Anchoring (invariant 9)
    anchor_rpc_url: str = ""
    anchor_private_key: SecretStr = SecretStr("")
    anchor_chain_id: int = 11155111
    anchor_batch_size: int = Field(default=20, ge=1)
    anchor_explorer_url: str = "https://sepolia.etherscan.io"

    @field_validator("anchor_chain_id")
    @classmethod
    def _testnet_only(cls, v: int) -> int:
        """Invariant 9: refuse any chain ID outside the testnet allow-list."""
        if v not in ANCHOR_CHAIN_ALLOWLIST:
            raise ValueError(f"ANCHOR_CHAIN_ID {v} is not an allow-listed testnet {sorted(ANCHOR_CHAIN_ALLOWLIST)}")
        return v

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
