"""Money-path tests for JTCC risk_manager.

These guard the rules that protect real capital:
  - 1% equity position sizing (and its clamps)
  - 6% daily drawdown shutdown
  - max concurrent / per-symbol trade caps
  - spread guard

risk_manager reads live state from a JSON file via `_read_state()`. Every test
monkeypatches that single function so no MT5 terminal or live file is touched.
"""
from pathlib import Path

import pytest

from trading_agents.jtcc.execution import risk_manager as rm


@pytest.fixture(autouse=True)
def _no_kill_switch(tmp_path, monkeypatch):
    """Point KILL_SWITCH at a non-existent file so can_trade() isn't blocked
    by a stray kill-switch on the dev machine, and pin the daily DD limit to its
    $200 default so a stray AGENT_DAILY_DD_USD in the env can't skew the math."""
    monkeypatch.setattr(rm, "KILL_SWITCH", tmp_path / "nope.json")
    monkeypatch.setenv("AGENT_DAILY_DD_USD", "200")


def _state(monkeypatch, **kwargs):
    monkeypatch.setattr(rm, "_read_state", lambda: kwargs)


# ── calculate_lot: 1% equity sizing ────────────────────────────────────────

def test_lot_forex_one_percent(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000, "balance": 10_000})
    # EURUSD 50-pip stop: risk $100 / ($0.0050 * 100_000 = $500/lot) = 0.20 lot
    lot, info = rm.calculate_lot("EURUSD", entry=1.1000, sl=1.0950, risk_pct=1.0)
    assert lot == pytest.approx(0.20)


def test_lot_gold_one_percent(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000, "balance": 10_000})
    # XAUUSD $5 stop: risk $100 / ($5 * 100oz = $500/lot) = 0.20 lot
    lot, _ = rm.calculate_lot("XAUUSD", entry=2000.0, sl=1995.0, risk_pct=1.0)
    assert lot == pytest.approx(0.20)


def test_lot_zero_when_no_account(monkeypatch):
    _state(monkeypatch)  # empty state -> equity 0
    lot, info = rm.calculate_lot("EURUSD", entry=1.1000, sl=1.0950)
    assert lot == 0.0
    assert "No account data" in info


def test_lot_zero_when_sl_too_close(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000})
    # 0.5-pip stop is below EURUSD min (8 pips) -> reject, never size a trade
    lot, info = rm.calculate_lot("EURUSD", entry=1.10000, sl=1.09995)
    assert lot == 0.0
    assert "SL too close" in info


def test_lot_clamps_to_max_ten(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000})
    # 100% risk would size huge; must clamp to 10.0 lots, never unbounded
    lot, _ = rm.calculate_lot("EURUSD", entry=1.1000, sl=1.0920, risk_pct=100.0)
    assert lot == 10.0


def test_lot_clamps_to_min_when_tiny(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000})
    lot, _ = rm.calculate_lot("EURUSD", entry=1.1000, sl=1.0950, risk_pct=0.001)
    assert lot == 0.01


def test_vol_scalar_clamped(monkeypatch):
    _state(monkeypatch, account={"equity": 10_000})
    base, _ = rm.calculate_lot("EURUSD", 1.1000, 1.0950, risk_pct=1.0)
    # scalar 99 must clamp to 5.0, not multiply lot by 99
    scaled, _ = rm.calculate_lot("EURUSD", 1.1000, 1.0950, risk_pct=1.0, vol_scalar=99.0)
    assert scaled == pytest.approx(min(base * 5.0, 10.0))


# ── check_daily_dd: fixed $200 shutdown (demo phase) ────────────────────────

def test_dd_shutdown_at_dollar_limit(monkeypatch):
    # $600 loss is past the $200 limit -> shutdown; pct still reported for display
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=-600.0)
    shutdown, pct = rm.check_daily_dd()
    assert shutdown is True
    assert pct == 6.0


def test_dd_no_shutdown_below_dollar_limit(monkeypatch):
    # $100 loss is under the $200 limit -> keep trading
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=-100.0)
    shutdown, pct = rm.check_daily_dd()
    assert shutdown is False
    assert pct == 1.0


def test_dd_ignores_positive_pnl(monkeypatch):
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=300.0)
    shutdown, pct = rm.check_daily_dd()
    assert shutdown is False
    assert pct == 0.0


def test_dd_safe_when_no_balance(monkeypatch):
    _state(monkeypatch)
    assert rm.check_daily_dd() == (False, 0.0)


# ── can_trade: concurrency + DD gates ──────────────────────────────────────

def test_can_trade_ok_when_flat(monkeypatch):
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=0.0, positions=[])
    allowed, reason = rm.can_trade("EURUSD")
    assert allowed is True
    assert reason == "OK"


def test_can_trade_blocked_by_dd(monkeypatch):
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=-700.0, positions=[])
    allowed, reason = rm.can_trade("EURUSD")
    assert allowed is False
    assert "SHUTDOWN" in reason


def test_can_trade_blocked_at_max_total(monkeypatch):
    positions = [{"symbol": s} for s in ("EURUSD", "GBPUSD", "USDJPY")]
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=0.0, positions=positions)
    allowed, reason = rm.can_trade("XAUUSD", max_total=3)
    assert allowed is False
    assert "Max 3 concurrent" in reason


def test_can_trade_fails_safe_on_corrupt_kill_switch(tmp_path, monkeypatch):
    # A kill-switch file that exists but won't parse must BLOCK trading,
    # never silently resume (fail-safe, not fail-open).
    ks = tmp_path / "ks.json"
    ks.write_text("{ this is not valid json")
    monkeypatch.setattr(rm, "KILL_SWITCH", ks)
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=0.0, positions=[])
    allowed, reason = rm.can_trade("EURUSD")
    assert allowed is False
    assert "failing safe" in reason.lower()


def test_can_trade_blocked_at_max_per_symbol(monkeypatch):
    positions = [{"symbol": "EURUSD"}, {"symbol": "EURUSD"}]
    _state(monkeypatch, account={"balance": 10_000}, daily_pnl=0.0, positions=positions)
    allowed, reason = rm.can_trade("EURUSD", max_per_symbol=2)
    assert allowed is False
    assert "EURUSD" in reason


# ── check_spread: skip economically-bad trades ─────────────────────────────

def test_spread_ok_at_threshold():
    ok, _ = rm.check_spread("EURUSD", entry=1.1000, sl=1.0950, spread=0.0010)  # 20%
    assert ok is True


def test_spread_skip_when_too_wide():
    ok, reason = rm.check_spread("EURUSD", entry=1.1000, sl=1.0950, spread=0.0011)  # 22%
    assert ok is False
    assert "skip" in reason.lower()
