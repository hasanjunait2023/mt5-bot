import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
from core.config import SYSTEM_CONFIG

router = APIRouter()

_ALLOWED_KEYS = {
    "account_balance", "max_risk_per_trade", "rr_ratio", "compound_on_equity",
    "symbols", "research_interval_hours", "optimization_interval_hours",
    "health_check_interval_minutes", "log_level",
    "enable_live_trading", "demo_account",
    "max_daily_trades", "max_daily_loss_pct", "max_drawdown_pct",
}


def _read_config() -> dict:
    if not SYSTEM_CONFIG.exists():
        return {}
    return json.loads(SYSTEM_CONFIG.read_text(encoding="utf-8"))


def _validate(data: dict) -> dict:
    errors = []
    if "max_risk_per_trade" in data:
        v = data["max_risk_per_trade"]
        if not (0.001 <= v <= 0.05):
            errors.append("max_risk_per_trade must be 0.001–0.05")
    if "symbols" in data:
        if not isinstance(data["symbols"], list) or len(data["symbols"]) == 0:
            errors.append("symbols must be a non-empty list")
    if "enable_live_trading" in data:
        if not isinstance(data["enable_live_trading"], bool):
            errors.append("enable_live_trading must be boolean")
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return data


@router.get("/settings")
def get_settings():
    return _read_config()


@router.put("/settings")
def put_settings(body: dict[str, Any]):
    unknown = set(body.keys()) - _ALLOWED_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown keys: {unknown}")
    _validate(body)
    cfg = _read_config()
    cfg.update(body)
    tmp = SYSTEM_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(SYSTEM_CONFIG)
    return cfg
