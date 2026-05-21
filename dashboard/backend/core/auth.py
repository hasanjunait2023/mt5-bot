"""
Lightweight, dependency-free auth for the dashboard backend.

Single-user model: one shared password (env var). On login the backend issues
an HMAC-signed, time-limited bearer token. The password/secret never leaves the
backend — only the signed token is held by the browser.

ENV-GATED & FAIL-OPEN-WHEN-UNCONFIGURED:
  - If DASHBOARD_PASSWORD is unset/empty  → auth is DISABLED (open, today's
    behavior). Existing local/VPS same-origin deploys keep working untouched.
  - If DASHBOARD_PASSWORD is set          → every /api route + the WebSocket
    require a valid token.

Env vars:
  DASHBOARD_PASSWORD         the login password (enables auth when set)
  DASHBOARD_SECRET           optional HMAC signing key; derived from the
                             password if omitted
  DASHBOARD_TOKEN_TTL_HOURS  token lifetime in hours (default 12)
"""

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import HTTPException, Request


def _password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "").strip()


def auth_enabled() -> bool:
    """Auth is only enforced once a password is configured."""
    return bool(_password())


def _signing_key() -> bytes:
    explicit = os.getenv("DASHBOARD_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    # derive deterministically from the password so no extra env is required
    return hashlib.sha256(b"mt5-dashboard-auth:" + _password().encode("utf-8")).digest()


def _ttl_seconds() -> int:
    try:
        return int(float(os.getenv("DASHBOARD_TOKEN_TTL_HOURS", "12")) * 3600)
    except ValueError:
        return 12 * 3600


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def check_password(candidate: str) -> bool:
    pw = _password()
    if not pw:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), pw.encode("utf-8"))


def mint_token() -> dict:
    """Issue a fresh signed token. Caller must have already checked the password."""
    exp = int(time.time()) + _ttl_seconds()
    payload = _b64e(json.dumps({"exp": exp}).encode("utf-8"))
    sig = _b64e(hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).digest())
    return {"token": f"{payload}.{sig}", "expires_at": exp}


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = _b64e(hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(_b64d(payload))
    except Exception:
        return False
    return int(data.get("exp", 0)) > int(time.time())


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


async def require_auth(request: Request) -> None:
    """FastAPI dependency. No-op when auth is disabled; else enforces a token."""
    if not auth_enabled():
        return
    if not verify_token(_extract_bearer(request)):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
