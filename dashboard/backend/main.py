import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, dotenv_values

from core.config import BASE_DIR

# Load project-root .env so DASHBOARD_PASSWORD/SECRET/etc. are honored both
# locally and on the VPS (uvicorn doesn't load .env on its own).
load_dotenv(BASE_DIR / ".env")

# The signals toggle must follow the .env file, not a stale value the
# orchestrator may have exported into our inherited environment (load_dotenv
# does not override existing env vars). Force just this one key from the file.
_dotenv = dotenv_values(BASE_DIR / ".env")
if "DASHBOARD_DISABLE_SIGNALS" in _dotenv and _dotenv["DASHBOARD_DISABLE_SIGNALS"] is not None:
    os.environ["DASHBOARD_DISABLE_SIGNALS"] = _dotenv["DASHBOARD_DISABLE_SIGNALS"]

from core.ws_manager import manager as ws_manager
from core.state_manager import poller
from core.log_tailer import tailer
from core.auth import require_auth, auth_enabled

from api import (
    overview, positions, history, agents, reports, logs, settings,
    ws, eas, dev_agents, system_agents, auth, cpp,
)
from api import telegram_hq as telegram_hq_api
from api import jtcc as jtcc_api
from api import signals as signals_api
from api import desk as desk_api
from api import system_time as system_time_api
from api import iconic as iconic_api
from api import journal as journal_api
from api import scalp as scalp_api
from api import vp as vp_api
from api import asia as asia_api
from api import fleet as fleet_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)


_signal_engine = None


def _maybe_start_signal_engine():
    """Spin up the signal engine in-process so WS push is zero-IPC.

    Env: DASHBOARD_DISABLE_SIGNALS=1 to skip (e.g. on a backend without MT5).
    """
    global _signal_engine
    if os.getenv("DASHBOARD_DISABLE_SIGNALS") == "1":
        logging.getLogger("uvicorn.error").info("Signal engine disabled by env")
        return
    try:
        import sys
        root = str(BASE_DIR)
        if root not in sys.path:
            sys.path.insert(0, root)
        from trading_agents.signal_engine import SignalEngine     # type: ignore
        _signal_engine = SignalEngine(broadcaster=ws_manager.broadcast_sync)
        _signal_engine.start()
        logging.getLogger("uvicorn.error").info("Signal engine started")
    except Exception as e:
        logging.getLogger("uvicorn.error").warning("Signal engine failed to start: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_manager.set_loop(asyncio.get_running_loop())
    poller.start()
    tailer.start()
    _maybe_start_signal_engine()
    yield
    if _signal_engine is not None:
        _signal_engine.stop()
    poller.stop()
    tailer.stop()


app = FastAPI(title="MT5 Dashboard API", lifespan=lifespan)

# CORS: if DASHBOARD_ALLOWED_ORIGINS is set (comma-separated), lock to it
# (plus localhost dev). Unset → "*" (today's behavior, back-compat).
_origins_env = os.getenv("DASHBOARD_ALLOWED_ORIGINS", "").strip()
if _origins_env:
    _allowed = [o.strip() for o in _origins_env.split(",") if o.strip()]
    _allowed += ["http://localhost:5173", "http://127.0.0.1:5173"]
else:
    _allowed = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.getLogger("uvicorn.error").info(
    "Dashboard auth: %s | CORS origins: %s",
    "ENABLED" if auth_enabled() else "DISABLED (set DASHBOARD_PASSWORD to enable)",
    _allowed,
)

# Auth endpoints are public (login/status must be reachable without a token).
app.include_router(auth.router, prefix="/api")

# Everything else requires a valid token *when auth is enabled*.
_protected = [Depends(require_auth)]
app.include_router(overview.router,      prefix="/api", dependencies=_protected)
app.include_router(positions.router,     prefix="/api", dependencies=_protected)
app.include_router(history.router,       prefix="/api", dependencies=_protected)
app.include_router(agents.router,        prefix="/api", dependencies=_protected)
app.include_router(reports.router,       prefix="/api", dependencies=_protected)
app.include_router(logs.router,          prefix="/api", dependencies=_protected)
app.include_router(settings.router,      prefix="/api", dependencies=_protected)
app.include_router(eas.router,           prefix="/api", dependencies=_protected)
app.include_router(dev_agents.router,    prefix="/api", dependencies=_protected)
app.include_router(system_agents.router, prefix="/api", dependencies=_protected)
app.include_router(cpp.router,           prefix="/api", dependencies=_protected)
app.include_router(telegram_hq_api.router, prefix="/api", dependencies=_protected)
app.include_router(jtcc_api.router,       prefix="/api", dependencies=_protected)
app.include_router(signals_api.router,    prefix="/api", dependencies=_protected)
app.include_router(desk_api.router,       prefix="/api", dependencies=_protected)
app.include_router(system_time_api.router, prefix="/api", dependencies=_protected)
app.include_router(iconic_api.router,     prefix="/api", dependencies=_protected)
app.include_router(journal_api.router,    prefix="/api", dependencies=_protected)
app.include_router(scalp_api.router,      prefix="/api", dependencies=_protected)
app.include_router(vp_api.router,         prefix="/api", dependencies=_protected)
app.include_router(asia_api.router,       prefix="/api", dependencies=_protected)
app.include_router(fleet_api.router,      prefix="/api", dependencies=_protected)

# WebSocket validates the token itself (browsers can't set WS headers).
app.include_router(ws.router)

# Serve the React production build when it exists.
# Build it once with: cd dashboard/frontend && npm run build
_dist = BASE_DIR / "dashboard" / "frontend" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    # Root-level static files the SPA needs at "/" (PWA manifest, service
    # worker, icons, favicon). The service worker in particular MUST be served
    # from the root with a JS content-type, or install/offline breaks.
    _ROOT_MEDIA = {".webmanifest": "application/manifest+json", ".js": "text/javascript"}

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path:
            candidate = (_dist / full_path).resolve()
            # Serve a real file if it exists and stays inside dist (no traversal).
            if candidate.is_file() and (candidate == _dist.resolve() or _dist.resolve() in candidate.parents):
                media = _ROOT_MEDIA.get(candidate.suffix)
                return FileResponse(str(candidate), media_type=media) if media else FileResponse(str(candidate))
        return FileResponse(str(_dist / "index.html"))
