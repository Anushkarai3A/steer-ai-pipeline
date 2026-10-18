from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import settings


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or base64.b16encode(__import__("os").urandom(8)).decode()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def _sign(payload: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def create_access_token(user_id: str, role: str, ttl_seconds: int | None = None) -> str:
    body = {
        "uid": user_id,
        "role": role,
        "exp": int(time.time()) + (ttl_seconds or settings.access_token_ttl_seconds),
    }
    raw = json.dumps(body).encode()
    return f"{base64.urlsafe_b64encode(raw).decode()}.{_sign(raw)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload_b64, signature = token.split(".", 1)
        raw = base64.urlsafe_b64decode(payload_b64.encode())
        if not hmac.compare_digest(_sign(raw), signature):
            return None
        body = json.loads(raw)
        if int(body.get("exp", 0)) < time.time():
            return None
        return body
    except Exception:
        return None
