# Dashboard Security Hardening — Implementation Hand-off

> Spec for the session implementing the auth hardening. The auth **foundation already exists**
> (`core/auth.py`, `api/auth.py`, `main.py` gating, `lib/api.ts`, `components/AuthGate.tsx`).
> This document refines it. Do **not** redesign the foundation — apply these deltas in order.

## Current state (baseline — do not re-derive)

| Layer | File | What it does today |
|---|---|---|
| Token core | `dashboard/backend/core/auth.py` | env-gated by `DASHBOARD_PASSWORD`; HMAC-SHA256 signed token `payload.sig`, payload = `{"exp":...}`; `check_password`/`verify_token` use `hmac.compare_digest`; `require_auth` reads `Authorization: Bearer`. |
| Login | `dashboard/backend/api/auth.py` | `GET /auth/status` (public), `POST /auth/login` → `mint_token()` in JSON body; in-proc global throttle `_FAILS["global"]`, 8 fails / 300 s. |
| Wiring | `dashboard/backend/main.py` | all `/api` routers get `Depends(require_auth)`; `auth` router public; CORS from `DASHBOARD_ALLOWED_ORIGINS` else `["*"]`, `allow_credentials=False`. |
| WS | `dashboard/backend/api/ws.py` | `verify_token(ws.query_params["token"])`, close 4401 on fail. |
| Frontend | `dashboard/frontend/src/lib/api.ts` | token in `localStorage`; `apiFetch` adds `Bearer`; `wsUrl` appends `?token=`; 401 → clear + `mt5-dash-unauthorized` event. |
| Login UI | `dashboard/frontend/src/components/AuthGate.tsx` | login screen; stores token via `setToken`. |

**Deployment assumption (verify before Phase 3):** reverse proxy (Coolify/nginx) terminates TLS and
serves built `dist` **same-origin** with `/api` + `/ws` proxied to uvicorn. If any path is plain
HTTP, the login password (POST body) is sniffable — fix TLS first or none of this matters.

---

## Execution order

```
Phase 0  Isolated quick wins      (headers, pw-length gate, fail-closed CORS)   — backend only, no protocol change
Phase 1  Throttle hardening       (lock + persist + Telegram alert)             — api/auth.py only
Phase 2  Token revocation         (token_version epoch)                          — core/auth.py + state file
Phase 3  Cookie migration + WS    (HttpOnly cookie; drop ?token=)               — ATOMIC FE+BE+proxy, staged rollout
Phase 4  Step-up confirm          (settings PUT + dev-trigger)                   — backend + small FE prompt
Phase 5  Network layer (Tailscale)                                              — ops runbook, no code
```

Phases 0–2 are independent and safe to ship one-by-one. Phase 3 is the big coordinated one and
subsumes the WS `?token=` removal. Phase 4 depends on Phase 3 only for the FE password prompt UX.

---

## Phase 0 — Isolated quick wins

### 0a. Security headers

New file `dashboard/backend/core/security_headers.py`:

```python
from starlette.middleware.base import BaseHTTPMiddleware

# CSP tuned to THIS app: Google Fonts (index.html), same-origin API/WS, inline
# styles (Tailwind runtime + style tag). Tighten further only after self-hosting fonts.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)

class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        r = await call_next(request)
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        r.headers["Content-Security-Policy"] = _CSP
        return r
```

`main.py`: `app.add_middleware(SecurityHeaders)` (add **before** CORS middleware so CORS headers are not overwritten).

**Gotcha:** the live page loads Google Fonts (`index.html` `<link>` to `fonts.googleapis.com`/
`fonts.gstatic.com`). The CSP above whitelists them. If you self-host fonts later, drop those
two origins and remove `'unsafe-inline'` from `style-src` only after verifying Tailwind's built
CSS needs no inline `<style>`. Test every page renders + charts (recharts injects inline styles —
keep `'unsafe-inline'` in `style-src`).

### 0b. Password-length startup gate

`core/auth.py`, add and call from `main.py` lifespan (before `yield`):

```python
MIN_PASSWORD_LEN = 12

def validate_auth_config() -> None:
    pw = _password()
    if pw and len(pw) < MIN_PASSWORD_LEN:
        raise RuntimeError(
            f"DASHBOARD_PASSWORD is set but shorter than {MIN_PASSWORD_LEN} chars — refuse to start."
        )
    if pw and not os.getenv("DASHBOARD_SECRET", "").strip():
        logging.getLogger("uvicorn.error").warning(
            "DASHBOARD_SECRET not set — signing key derived from password. "
            "Set an independent random DASHBOARD_SECRET in production."
        )
```

Fail-fast is correct here: a 4-char password silently weakens the HMAC signing key.

### 0c. Fail-closed CORS default

`main.py`, replace the `else: _allowed = ["*"]` branch:

```python
if _origins_env:
    _allowed = [o.strip() for o in _origins_env.split(",") if o.strip()]
    _allowed += ["http://localhost:5173", "http://127.0.0.1:5173"]
elif auth_enabled():
    # password set but origins unset → same-origin only (no cross-origin)
    _allowed = ["http://localhost:5173", "http://127.0.0.1:5173"]
else:
    _allowed = ["*"]   # unchanged: open dev/back-compat when no password
```

Same-origin requests don't trigger CORS, so the same-origin VPS dashboard keeps working with an
empty cross-origin allowlist. **Coupled with Phase 3:** once cookies are used, `allow_credentials`
becomes `True` and `["*"]` is *invalid* — Phase 0c makes "auth on ⇒ explicit origins" the norm,
so Phase 3 just flips `allow_credentials`.

---

## Phase 1 — Throttle hardening (`api/auth.py`)

Problems today: lock-free dict mutated from sync route (racy), single global bucket (attacker
locks out owner), wiped on every `systemctl restart` (deploy = reset).

```python
import json, threading, time
from pathlib import Path
from core.config import BASE_DIR

_THROTTLE_FILE = BASE_DIR / "logs" / "_auth_throttle.json"
_LOCK = threading.Lock()
_WINDOW_S = 300
_MAX_FAILS = 8
_LOCKOUT_BASE_S = 60   # exponential: 60s, 120s, 240s ... per consecutive lockout

def _load() -> dict:
    try: return json.loads(_THROTTLE_FILE.read_text())
    except Exception: return {"fails": [], "lockouts": 0, "locked_until": 0}

def _save(d: dict) -> None:
    _THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _THROTTLE_FILE.write_text(json.dumps(d))

def _alert(msg: str) -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level="WARNING")
    except Exception:
        pass   # notifier optional; never block login on it
```

`login()` becomes (single-user → global bucket is acceptable once persisted + lock-guarded;
do NOT key by client IP — behind the proxy every request shares one IP unless you trust
`X-Forwarded-For`, which is spoofable):

```python
with _LOCK:
    st = _load(); now = time.time()
    if now < st.get("locked_until", 0):
        raise HTTPException(429, "Locked out — try again later")
    st["fails"] = [t for t in st["fails"] if now - t < _WINDOW_S]
    if not check_password(req.password):
        st["fails"].append(now)
        if len(st["fails"]) >= _MAX_FAILS:
            st["lockouts"] += 1
            st["locked_until"] = now + _LOCKOUT_BASE_S * (2 ** (st["lockouts"] - 1))
            st["fails"] = []
            _alert(f"🔒 Dashboard: {_MAX_FAILS} failed logins — locked for "
                    f"{int(st['locked_until']-now)}s (lockout #{st['lockouts']}).")
        _save(st)
        raise HTTPException(401, "Incorrect password")
    st["fails"] = []; st["lockouts"] = 0; st["locked_until"] = 0
    _save(st)
return {"auth_required": True, **mint_token()}
```

**Gotcha:** `notifier` import path — the dashboard process must be able to import
`trading_agents.dev_agents.notifier`. `supervisor_agent.py` does the same import; mirror its
`try/except` (already shown). Add `logs/_auth_throttle.json` to `.gitignore` (it's runtime state).

---

## Phase 2 — Token revocation (`core/auth.py`)

Stateless tokens can't be killed before TTL. Add a server-side epoch mixed into the signature
payload; bumping it invalidates every existing token (password change, "log out everywhere",
suspected leak). File-based to match the codebase's JSON-state convention.

```python
_EPOCH_FILE = BASE_DIR / "logs" / "_auth_epoch.json"

def _epoch() -> int:
    try: return int(json.loads(_EPOCH_FILE.read_text())["v"])
    except Exception: return 0

def bump_epoch() -> int:
    e = _epoch() + 1
    _EPOCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _EPOCH_FILE.write_text(json.dumps({"v": e}))
    return e
```

- `mint_token()`: payload becomes `{"exp": exp, "iat": int(time.time()), "v": _epoch()}`.
- `verify_token()`: after signature + exp checks, also require `data.get("v") == _epoch()`.
- Add authenticated `POST /api/auth/logout-all` → `bump_epoch()`; wire a "Sign out everywhere"
  control in `AuthGate`/TopBar. Call `bump_epoch()` automatically on password change too.

**Sequencing:** Phase 2 changes the token payload; Phase 3 also touches mint/verify. Do Phase 2
**before** Phase 3 (or together) so the payload schema is edited once. `iat` added now also
enables "reject tokens issued before last password change" later if you prefer that to epoch.

---

## Phase 3 — Cookie migration + WS (ATOMIC, staged rollout)

**Goal:** token in `HttpOnly; Secure; SameSite=Strict` cookie instead of `localStorage`
(kills XSS token-theft → which today grants `PUT /settings` live-trading control). Same-origin
WS then authenticates from the cookie → `?token=` removed (it leaks via proxy logs / history).

### Staged rollout (zero-downtime, reversible)

1. **Backend first** — accept **both** cookie and bearer; set cookie on login *and* still return
   token in body. Deploy. (Old FE keeps working on bearer; nothing breaks.)
2. **Frontend next** — switch to cookie (`credentials: 'include'`, stop reading/sending token,
   WS without `?token=`). Deploy.
3. **Backend cleanup** — drop bearer acceptance + token-in-body (keep bearer only if the optional
   `VITE_API_BASE` split-origin/Vercel mode is actually used — see cross-origin gotcha).

Rollback at any step = redeploy previous artifact; step 1 is a superset so safe.

### Backend — `core/auth.py`

```python
COOKIE_NAME = "mt5_dash"

def _extract_token(request: Request) -> str | None:
    tok = request.cookies.get(COOKIE_NAME)
    if tok: return tok
    h = request.headers.get("Authorization", "")          # transition fallback
    return h[7:].strip() if h.startswith("Bearer ") else None

def set_auth_cookie(resp, token: str) -> None:
    resp.set_cookie(COOKIE_NAME, token, max_age=_ttl_seconds(),
                     httponly=True, secure=True, samesite="strict", path="/")

def clear_auth_cookie(resp) -> None:
    resp.delete_cookie(COOKIE_NAME, path="/")
```

`require_auth` uses `_extract_token`. **`secure=True` requires HTTPS** — for localhost dev over
HTTP gate it: `secure=not _is_dev()` (e.g. env `DASHBOARD_DEV=1`), else the cookie is never sent
in dev and you lock yourself out.

### Backend — `api/auth.py`

`/auth/login` signature → `def login(req: LoginRequest, response: Response)`; on success call
`set_auth_cookie(response, mint_token()["token"])`. During stage 1 also return the token in body;
remove in stage 3. Add `POST /auth/logout` → `clear_auth_cookie(response)`.

### Backend — `main.py` CORS (COUPLED — must change together)

```python
allow_credentials=True,          # cookies require this
# allow_origins MUST be an explicit list — "*" is INVALID with credentials.
```

Phase 0c already removed the `"*"` default when auth is on. If `VITE_API_BASE` cross-origin mode
is used you **must** set `DASHBOARD_ALLOWED_ORIGINS` to the exact frontend origin (no wildcard).

### Backend — `api/ws.py`

```python
tok = ws.cookies.get("mt5_dash") or ws.query_params.get("token")  # cookie first
if auth_enabled() and not verify_token(tok):
    await ws.close(code=4401); return
```

Same-origin WS sends the cookie automatically. Keep the `?token=` fallback **only** for the
cross-origin split mode (a cross-site WS will not send the cookie).

### Frontend — `lib/api.ts`

- `apiFetch`: add `credentials: 'include'`; stop setting `Authorization`; keep the 401 →
  `clearToken()` + `mt5-dash-unauthorized` event.
- `wsUrl`: do **not** append `?token=` in same-origin mode (cookie carries it). Keep the
  `?token=` branch only when `API_BASE`/`VITE_WS_BASE` indicates cross-origin.
- `getToken/setToken/clearToken`: become no-ops for cookie mode; on first load actively delete
  the legacy `mt5_dash_token` localStorage key (cleanup; it's now dead + an XSS target).

### Frontend — `components/AuthGate.tsx`

Login no longer stores a token: POST `/auth/login`, on 200 the cookie is set by the browser →
just flip to the app (re-fetch `/auth/status` or optimistically render; a failing `apiFetch`
will re-trigger the unauthorized event). Add a "Sign out" action → `POST /auth/logout` then
show the gate.

### Phase 3 gotchas

- **TLS is mandatory.** `Secure` cookies are dropped over HTTP. Confirm proxy TLS + HSTS first.
- **Proxy config:** ensure the reverse proxy forwards `Cookie` (default) and, for `/ws`, the
  `Upgrade`/`Connection` headers; do not strip `Set-Cookie`. If the proxy rewrites paths set
  `proxy_cookie_path` accordingly. Document the exact nginx/Coolify block used.
- **`SameSite=Strict`** is correct for a directly-navigated SPA dashboard. Don't use `Lax`
  unless a future flow needs cross-site top-level GETs.
- **CSRF:** with `SameSite=Strict` + JSON-only API + no cookie auth on cross-site forms, CSRF
  risk is minimal; if you ever relax SameSite, add a double-submit CSRF token for the mutating
  routes (`PUT /settings`, `/dev-agents/trigger`).
- **No `allow_origins=["*"]` with `allow_credentials=True`** — the browser rejects it silently;
  every request will look "blocked by CORS." This is the #1 implementation trap.

---

## Phase 4 — Step-up confirmation for dangerous endpoints

`PUT /settings` (can flip `enable_live_trading`, change risk %) and `POST /dev-agents/trigger`
(spawns the autonomous coding agent) share the same token as read-only views. Single-user →
RBAC is overkill; require a fresh password header on just these two.

`core/auth.py`:

```python
async def require_step_up(request: Request) -> None:
    if not auth_enabled(): return
    if not check_password(request.headers.get("X-Confirm-Password", "")):
        raise HTTPException(403, "Re-enter password to confirm this action")
```

Apply `Depends(require_step_up)` to the `PUT /settings` route and the dev-trigger route only
(in addition to `require_auth`). Then **audit-log + Telegram-notify** every settings change and
every trigger (reuse the Phase 1 `_alert`/notifier) — a stolen read token can't silently change
live trading, and you get a record either way.

**Frontend:** Settings "Save" and the dev-trigger button prompt for the password, send it as
`X-Confirm-Password` for that one request, never store it.

**Gotcha:** `check_password` is constant-time already (`hmac.compare_digest`) — keep it; do not
add a plain `==` path.

---

## Phase 5 — Network layer (ops runbook, recommended primary)

App-token auth should be the *second* wall. For a single user, the strongest + cheapest control
is to remove public internet exposure entirely.

1. Install Tailscale on the VPS: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`.
2. Bind uvicorn to loopback — systemd unit `ExecStart`: add `--host 127.0.0.1` (and keep the
   chosen port, e.g. 8001).
3. Reach the dashboard via the tailnet (MagicDNS name / 100.x address) from your devices.
4. Close the public port at the VPS firewall (`ufw deny <port>`); keep only SSH + Tailscale.

Result: no public attack surface, no CORS concerns, tailnet provides device auth/MFA. The
cookie/token work above becomes pure defense-in-depth. **Tradeoff:** lose browser access from
non-tailnet devices — acceptable for a personal dashboard; if public access is a hard
requirement, skip Phase 5 and rely on Phases 0–4 + TLS.

---

## Verification checklist (run after each phase)

- [ ] `DASHBOARD_PASSWORD` unset → everything works token-free (back-compat preserved).
- [ ] Password set, no token → every `/api` route 401, `/auth/status` + `/auth/login` reachable.
- [ ] Valid login → all pages load, WS connects, charts render (CSP not blocking recharts/fonts).
- [ ] Wrong password ×8 → 429 lockout; lockout survives `systemctl restart mt5-dashboard`
      (Phase 1); Telegram alert received.
- [ ] `bump_epoch()` / logout-all → previously valid token now 401 (Phase 2).
- [ ] DevTools: token in cookie, cookie is `HttpOnly`+`Secure`+`SameSite=Strict`, **not** in
      `localStorage`; WS URL has no `?token=` (Phase 3).
- [ ] `PUT /settings` / dev-trigger without `X-Confirm-Password` → 403 (Phase 4).
- [ ] `curl -I` shows CSP / X-Frame-Options / nosniff; dashboard not embeddable in an iframe.
- [ ] Cross-origin probe from a random origin is blocked (CORS locked).
- [ ] Backend import check: `python -c "from api import auth, ws, settings, dev_agents, system_agents"`.
- [ ] `npx tsc --noEmit` + `npm run build` clean.

## Rollback

Phases 0–2: revert the single file + redeploy. Phase 3: staged (step 1 accepts both schemes —
revert FE or BE independently). Phase 4: remove the `Depends(require_step_up)` lines. Phase 5:
`tailscale down` + reopen firewall + drop `--host 127.0.0.1`.
