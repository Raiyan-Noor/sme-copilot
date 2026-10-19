"""Runtime settings, read from the environment and the repo-root .env (gitignored).

Secrets (API keys, ANCHOR_PRIVATE_KEY, the Gmail client secret and token key) are SecretStr so they never appear in reprs or logs. The anchor chain ID is
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
    # Written by `make redteam`; the Trust screen shows it as is.
    redteam_results: Path = REPO_ROOT / "docs" / "results" / "redteam.json"
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
    llm_timeout_s: float = Field(default=60.0, gt=0)
    gemini_model: str = "gemini-2.5-flash"
    # Recorded responses (committed) that CI replays; also the anchoring RPC mock later.
    llm_replay_dir: Path = REPO_ROOT / "backend" / "data" / "replay"

    # Anchoring (invariant 9)
    anchor_rpc_url: str = ""
    anchor_private_key: SecretStr = SecretStr("")
    anchor_chain_id: int = 11155111
    anchor_batch_size: int = Field(default=20, ge=1)
    anchor_explorer_url: str = "https://sepolia.etherscan.io"
    # Record/replay for the anchoring RPC; defaults to LLM_REPLAY. Replay never sends (CI); record sends live and
    # stores what the chain returned, so tests can verify real anchors offline.
    anchor_replay: Literal["record", "replay", "off"] | None = None
    anchor_replay_dir: Path | None = None  # defaults to llm_replay_dir (namespace rpc/)
    # Automatic triggers (every ANCHOR_BATCH_SIZE entries, end of a demo scenario). "Anchor now" works regardless.
    anchor_auto: bool = True
    # Send from a worker thread so core flows never wait on the RPC. Tests turn it off to run deterministically.
    anchor_background: bool = True

    # Gmail (real inbox via OAuth). Unset client ID = the "Connect Gmail" button explains it is not configured.
    gmail_client_id: str = ""
    gmail_client_secret: SecretStr = SecretStr("")
    # Must match the redirect URI registered on the OAuth client in Google Cloud.
    gmail_redirect_uri: str = "http://localhost:8000/inbox/gmail/callback"
    # 64 hex chars (32 bytes): encrypts each business's Gmail refresh token at rest.
    gmail_token_key: SecretStr = SecretStr("")
    # Background poll of connected inboxes (history API from the last seen historyId). Tests poll by hand.
    gmail_poll: bool = True
    gmail_poll_seconds: float = Field(default=7.0, ge=2.0)
    # Comma-separated addresses real Gmail sends may go to; anything else lands in the simulated outbox, labelled.
    demo_send_allowlist: str = ""
    # Where the OAuth popup's "connected" message is posted; defaults to the first ALLOWED_ORIGINS entry.
    frontend_url: str = ""

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

    @property
    def send_allowlist(self) -> frozenset[str]:
        return frozenset(a.strip().lower() for a in self.demo_send_allowlist.split(",") if a.strip())

    @property
    def frontend_origin(self) -> str:
        return (self.frontend_url or (self.origins[0] if self.origins else "")).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
