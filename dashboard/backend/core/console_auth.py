"""
Dedicated auth for the Claude Code Console — DELIBERATELY separate and stronger
than the dashboard auth (core/auth.py), because the console grants arbitrary code
execution + file edits + bash on the live trading VPS.

Two independent gates, BOTH must pass when the console is enabled:
  1. IP allowlist   — CONSOLE_ALLOWED_IPS (comma list of IPs/CIDRs). Enforced on
                      every console route incl. login + the WebSocket.
  2. Bearer token   — minted from CONSOLE_PASSWORD (separate from DASHBOARD_PASSWORD,
                      so a leaked dashboard token can NOT reach code execution).

Fail-CLOSED: if CONSOLE_PASSWORD is unset the console is fully disabled (404/403),
not open. This is the opposite default of the dashboard (which fails open) — RCE
must be opt-in.

Env:
  CONSOLE_PASSWORD          enables the console when set (required)
  CONSOLE_SECRET            optional HMAC key (derived from password if omitted)
  CONSOLE_ALLOWED_IPS       comma list of allowed client IPs / CIDRs (empty = any IP,
                            token still required — a warning is logged)
  CONSOLE_TRUST_XFF         "1" → read client IP from X-Forwarded-For first hop
  CONSOLE_TOKEN_TTL_HOURS   token lifetime (default 12)
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import time

from fastapi import HTTPException, Request, WebSocket

log = logging.getLogger("console.auth")


def _password() -> str:
    return os.getenv("CONSOLE_PASSWORD", "").strip()


def console_enabled() -> bool:
    return bool(_password())


def _signing_key() -> bytes:
    explicit = os.getenv("CONSOLE_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    return hashlib.sha256(b"mt5-console-auth:" + _password().encode("utf-8")).digest()


def _ttl_seconds() -> int:
    try:
        return int(float(os.getenv("CONSOLE_TOKEN_TTL_HOURS", "12")) * 3600)
    except ValueError:
        return 12 * 3600


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def check_password(candidate: str) -> bool:
    pw = _password()
    return bool(pw) and hmac.compare_digest(candidate.encode("utf-8"), pw.encode("utf-8"))


def mint_token() -> dict:
    exp = int(time.time()) + _ttl_seconds()
    payload = _b64e(json.dumps({"exp": exp, "scope": "console"}).encode("utf-8"))
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
    return data.get("scope") == "console" and int(data.get("exp", 0)) > int(time.time())


# ── IP allowlist ────────────────────────────────────────────────────────────
def _allowed_nets() -> list:
    raw = os.getenv("CONSOLE_ALLOWED_IPS", "").strip()
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("CONSOLE_ALLOWED_IPS: ignoring invalid entry %r", part)
    return nets


def client_ip(scope_client_host: str | None, headers) -> str:
    """Resolve the real client IP. Honors X-Forwarded-For only when explicitly trusted."""
    if os.getenv("CONSOLE_TRUST_XFF") == "1":
        xff = headers.get("x-forwarded-for") if headers else None
        if xff:
            return xff.split(",")[0].strip()
    return scope_client_host or ""


def ip_allowed(ip: str) -> bool:
    nets = _allowed_nets()
    if not nets:
        # No allowlist configured: token still required, but warn loudly.
        log.warning("CONSOLE_ALLOWED_IPS empty — console reachable from ANY IP (token-only)")
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


# ── FastAPI guards ──────────────────────────────────────────────────────────
def _req_ip(request: Request) -> str:
    return client_ip(request.client.host if request.client else None, request.headers)


def guard_ip(request: Request) -> None:
    """IP gate for plaintext console routes (login/status). Console must be enabled."""
    if not console_enabled():
        raise HTTPException(status_code=404, detail="Console disabled")
    if not ip_allowed(_req_ip(request)):
        raise HTTPException(status_code=403, detail="IP not allowed")


def _bearer(request: Request) -> str | None:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else None


async def require_console(request: Request) -> None:
    """Full gate (IP + token) for authenticated console routes."""
    guard_ip(request)
    if not verify_token(_bearer(request)):
        raise HTTPException(status_code=401, detail="Invalid or missing console token")


def ws_authorized(ws: WebSocket, token: str | None) -> bool:
    """IP + token gate for the console WebSocket."""
    if not console_enabled():
        return False
    ip = client_ip(ws.client.host if ws.client else None, ws.headers)
    return ip_allowed(ip) and verify_token(token)
