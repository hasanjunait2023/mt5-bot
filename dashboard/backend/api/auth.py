"""Auth endpoints — login and a public status probe. Both are unauthenticated."""

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.auth import auth_enabled, check_password, mint_token

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


# simple in-process throttle to blunt brute force
_FAILS: dict[str, list[float]] = {}
_WINDOW_S = 300
_MAX_FAILS = 8


@router.get("/auth/status")
def auth_status():
    """Tells the frontend whether it must show a login screen. Always public."""
    return {"auth_required": auth_enabled()}


@router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    if not auth_enabled():
        # nothing to log into — auth is disabled
        return {"auth_required": False, "token": None}

    client_ip = (request.client.host if request.client else None) or "unknown"
    now = time.time()
    fails = [t for t in _FAILS.get(client_ip, []) if now - t < _WINDOW_S]
    if len(fails) >= _MAX_FAILS:
        raise HTTPException(status_code=429, detail="Too many attempts — wait a few minutes")

    if not check_password(req.password):
        fails.append(now)
        _FAILS[client_ip] = fails
        raise HTTPException(status_code=401, detail="Incorrect password")

    _FAILS.pop(client_ip, None)
    return {"auth_required": True, **mint_token()}
