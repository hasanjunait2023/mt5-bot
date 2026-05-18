import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.ws_manager import manager as ws_manager
from core.state_manager import poller
from core.log_tailer import tailer

from api import overview, positions, history, agents, reports, logs, settings, ws, eas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_manager.set_loop(asyncio.get_running_loop())
    poller.start()
    tailer.start()
    yield
    poller.stop()
    tailer.stop()


app = FastAPI(title="MT5 Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(eas.router, prefix="/api")
app.include_router(ws.router)
