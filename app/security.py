from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional


def generate_upload_token() -> str:
    return "cov_" + secrets.token_urlsafe(32)


def hash_upload_token(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def verify_upload_token(token: str, pepper: str, expected_hash: Optional[str]) -> bool:
    if not expected_hash:
        return False
    actual = hash_upload_token(token, pepper)
    return hmac.compare_digest(actual, expected_hash)


def verify_github_signature(payload: bytes, signature_header: Optional[str], secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(provided, expected)

