"""Runtime settings, read from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    # LLM (any LangChain "provider:model" string)
    model: str = field(default_factory=lambda: _env("AGENT_MODEL", "anthropic:claude-sonnet-5-5"))

    # Notion
    notion_token: str = field(default_factory=lambda: _env("NOTION_TOKEN"))
    notion_database_id: str = field(default_factory=lambda: _env("NOTION_DATABASE_ID"))
    notion_data_source_id: str = field(default_factory=lambda: _env("NOTION_DATA_SOURCE_ID"))

    # Gmail (our read-only MCP server)
    gmail_token_path: str = field(
        default_factory=lambda: _env("GMAIL_TOKEN_PATH", str(ROOT / "secrets" / "gmail_token.json"))
    )
    gmail_client_secret_path: str = field(
        default_factory=lambda: _env(
            "GMAIL_CLIENT_SECRET_PATH", str(ROOT / "secrets" / "gmail_client_secret.json")
        )
    )

    # Files / state
    state_db: str = field(default_factory=lambda: _env("AGENT_STATE_DB", str(ROOT / "data" / "agent_state.db")))
    checkpoint_db: str = field(default_factory=lambda: _env("AGENT_CHECKPOINT_DB", str(ROOT / "data" / "checkpoints.db")))
    master_resume: str = field(default_factory=lambda: _env("MASTER_RESUME", str(ROOT / "resume" / "master_resume.json")))
    resume_out_dir: str = field(default_factory=lambda: _env("RESUME_OUT_DIR", str(ROOT / "data" / "resumes")))
    resume_public_base_url: str = field(default_factory=lambda: _env("RESUME_PUBLIC_BASE_URL"))

    # Behaviour
    timezone: str = field(default_factory=lambda: _env("AGENT_TIMEZONE", "Asia/Kolkata"))
    discovery_cron: str = field(default_factory=lambda: _env("DISCOVERY_CRON", "0 7 * * *"))
    inbox_cron: str = field(default_factory=lambda: _env("INBOX_CRON", "0 8 * * *"))
    poll_minutes: int = field(default_factory=lambda: int(_env("POLL_MINUTES", "10")))
    max_new_jobs_per_run: int = field(default_factory=lambda: int(_env("MAX_NEW_JOBS_PER_RUN", "25")))
    max_revision_rounds: int = field(default_factory=lambda: int(_env("MAX_REVISION_ROUNDS", "3")))
    stuck_minutes: int = field(default_factory=lambda: int(_env("STUCK_MINUTES", "45")))

    # Alerts / liveness
    healthcheck_url: str = field(default_factory=lambda: _env("HEALTHCHECK_URL"))

    def ensure_dirs(self) -> None:
        for p in (self.state_db, self.checkpoint_db):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(self.resume_out_dir).mkdir(parents=True, exist_ok=True)
