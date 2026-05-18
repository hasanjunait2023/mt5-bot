"""
Dashboard Backend — FastAPI entry point.
Usage: uvicorn dashboard.backend.api:app --reload
       (from project root: c:\\Users\\Junait\\mt5 bot)
"""
import sys
import os
from pathlib import Path

# Make sure mt5_bridge and trading_agents are importable
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mt5_bridge"))

# Add backend folder so sub-modules use bare imports (core.xxx, api.xxx)
BACKEND = Path(__file__).parent
sys.path.insert(0, str(BACKEND))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.state_manager import poller
from core.log_tailer import tailer
from api.overview  import router as overview_router
from api.positions import router as positions_router
from api.history   import router as history_router
from api.agents    import router as agents_router
from api.logs      import router as logs_router
from api.settings  import router as settings_router
from api.ws        import router as ws_router

app = FastAPI(
    title="MT5 Trading Bot Dashboard",
    description="Real-time monitoring for the MTF EMA Alignment Scalper",
    version="1.0.0",
)

# Allow React dev server (localhost:3000) and same-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(overview_router,  prefix="/api")
app.include_router(positions_router, prefix="/api")
app.include_router(history_router,   prefix="/api")
app.include_router(agents_router,    prefix="/api")
app.include_router(logs_router,      prefix="/api")
app.include_router(settings_router,  prefix="/api")
app.include_router(ws_router)        # WebSocket at /ws


@app.on_event("startup")
async def startup():
    poller.start()
    tailer.start()


@app.on_event("shutdown")
async def shutdown():
    poller.stop()
    tailer.stop()


@app.get("/health")
def health():
    return {"status": "ok", "trader": poller.get_snapshot().get("trader_running", False)}
