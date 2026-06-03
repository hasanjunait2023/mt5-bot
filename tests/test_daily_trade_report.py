"""Tests for the EOD daily trade report builder (pure, no journal/telegram I/O)."""
from datetime import datetime, timezone

from trading_agents import daily_trade_report as dtr

# 17:00 UTC == 23:00 BD on 2026-06-03 — the report's fire time.
NOW = datetime(2026, 6, 3, 17, 0, 0, tzinfo=timezone.utc)


def rec(**kw):
    base = dict(
        agent="MTF", source="MTF_EMA", symbol="EURUSD", direction="BUY",
        strategies=["MTF EMA"], outcome="TP_HIT", pnl=10.0,
        close_time="2026-06-03T15:00:00+00:00",
        open_time="2026-06-03T13:00:00+00:00",
    )
    base.update(kw)
    return base


def test_no_trades_message():
    assert "No trades taken today" in dtr.build_report([], NOW)


def test_excludes_other_bd_days():
    y = rec(close_time="2026-06-02T15:00:00+00:00", open_time="2026-06-02T13:00:00+00:00")
    assert "No trades taken today" in dtr.build_report([y], NOW)


def test_overview_pnl_and_winrate():
    recs = [rec(pnl=20.0, outcome="TP_HIT"),
            rec(pnl=-8.0, outcome="SL_HIT", symbol="GBPUSD")]
    msg = dtr.build_report(recs, NOW)
    assert "1W / 1L" in msg
    assert "+$12.00" in msg


def test_loss_shows_reason_strategy_rationale():
    recs = [rec(pnl=-8.0, outcome="SL_HIT", symbol="GBPUSD", agent="JTCC",
                strategies=["s11"], actual_rr=-1.0, rationale="swept London high")]
    msg = dtr.build_report(recs, NOW)
    assert "stop loss hit" in msg
    assert "JTCC" in msg
    assert "s11" in msg
    assert "swept London high" in msg


def test_groups_by_agent():
    recs = [rec(agent="MTF", pnl=20.0, outcome="TP_HIT"),
            rec(agent="JTCC", pnl=-8.0, outcome="SL_HIT")]
    msg = dtr.build_report(recs, NOW)
    assert "MTF" in msg and "JTCC" in msg


def test_demo_trades_excluded_by_default():
    recs = [rec(pnl=20.0, outcome="TP_HIT", demo=True)]
    assert "No trades taken today" in dtr.build_report(recs, NOW)
