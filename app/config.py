from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app"
    )
    storage_root: str = os.getenv("STORAGE_ROOT", "./storage")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    upload_token_pepper: str = os.getenv("UPLOAD_TOKEN_PEPPER", "local-dev-pepper")
    github_webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "local-dev-secret")
    github_app_id: str = os.getenv("GITHUB_APP_ID", "")
    github_private_key_path: str = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
    admin_token: str = os.getenv("ADMIN_TOKEN", "local-dev-admin")
    github_commit_status_enabled: bool = env_bool("GITHUB_COMMIT_STATUS_ENABLED", True)
    patch_coverage_minimum: float = float(os.getenv("PATCH_COVERAGE_MINIMUM", "0.8"))


def get_settings() -> Settings:
    return Settings()
