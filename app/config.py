from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_env_file(path: Path | None = None) -> None:
    env_path = path or Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


load_env_file()


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app"
        )
    )
    storage_root: str = field(default_factory=lambda: os.getenv("STORAGE_ROOT", "./storage"))
    public_base_url: str = field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    )
    upload_token_pepper: str = field(
        default_factory=lambda: os.getenv("UPLOAD_TOKEN_PEPPER", "local-dev-pepper")
    )
    github_webhook_secret: str = field(
        default_factory=lambda: os.getenv("GITHUB_WEBHOOK_SECRET", "local-dev-secret")
    )
    github_app_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_ID", ""))
    github_private_key_path: str = field(
        default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
    )
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", "local-dev-admin"))
    github_commit_status_enabled: bool = field(
        default_factory=lambda: env_bool("GITHUB_COMMIT_STATUS_ENABLED", True)
    )
    patch_coverage_minimum: float = field(
        default_factory=lambda: float(os.getenv("PATCH_COVERAGE_MINIMUM", "0.8"))
    )


def get_settings() -> Settings:
    return Settings()
