"""Fail-closed tests for the demo->LIVE promotion gate.

can_go_live() is the single guard between a strategy and real money. It must
be FAIL-CLOSED: any missing or insufficient evidence => not allowed. These
tests pin that contract so a future refactor can't silently open the gate.

The gate reads three JSON files via `_read(path)`. We monkeypatch `_read` to
return controlled data keyed by which module path was requested.
"""
import pytest

from trading_agents import promotion_gate as pg


def _wire(monkeypatch, coach=None, validator=None, config=None):
    coach = coach or {}
    validator = validator or {}
    config = config or {}

    def fake_read(path):
        if path == pg._COACH:
            return coach
        if path == pg._VALIDATOR:
            return validator
        if path == pg._CONFIG:
            return config
        return {}

    monkeypatch.setattr(pg, "_read", fake_read)


def _good_coach(ea="S6"):
    return {"eas": {ea: {"days_on_demo": 10, "total_trades_on_demo": 50}}}


def _good_validator(ea="S6"):
    return {"ea": ea, "tested_at": "2026-06-01T00:00:00Z", "overall_verdict": "PASS"}


def test_blocked_when_no_track_record(monkeypatch):
    _wire(monkeypatch, coach={})
    ok, reasons = pg.can_go_live("S6")
    assert ok is False
    assert any("No demo track record" in r for r in reasons)


def test_allowed_when_all_evidence_present(monkeypatch):
    _wire(monkeypatch, coach=_good_coach(), validator=_good_validator())
    ok, _ = pg.can_go_live("S6")
    assert ok is True


def test_blocked_when_demo_too_short(monkeypatch):
    coach = {"eas": {"S6": {"days_on_demo": 2, "total_trades_on_demo": 50}}}
    _wire(monkeypatch, coach=coach, validator=_good_validator())
    ok, reasons = pg.can_go_live("S6")
    assert ok is False
    assert any("soak too short" in r for r in reasons)


def test_blocked_when_too_few_trades(monkeypatch):
    coach = {"eas": {"S6": {"days_on_demo": 10, "total_trades_on_demo": 10}}}
    _wire(monkeypatch, coach=coach, validator=_good_validator())
    ok, reasons = pg.can_go_live("S6")
    assert ok is False
    assert any("Too few demo trades" in r for r in reasons)


def test_blocked_when_validator_missing(monkeypatch):
    _wire(monkeypatch, coach=_good_coach(), validator={})
    ok, reasons = pg.can_go_live("S6")
    assert ok is False
    assert any("No fresh EAValidator" in r for r in reasons)


def test_blocked_when_validator_is_for_other_ea(monkeypatch):
    _wire(monkeypatch, coach=_good_coach("S6"), validator=_good_validator("S99"))
    ok, _ = pg.can_go_live("S6")
    assert ok is False


def test_blocked_on_conditional_pass(monkeypatch):
    """CONDITIONAL_PASS is NOT PASS — must stay blocked (the 'Elite 75% WR'
    trap: anything short of a clean PASS cannot touch real money)."""
    val = {"ea": "S6", "tested_at": "2026-06-01", "overall_verdict": "CONDITIONAL_PASS"}
    _wire(monkeypatch, coach=_good_coach(), validator=val)
    ok, reasons = pg.can_go_live("S6")
    assert ok is False
    assert any("must be PASS" in r for r in reasons)


def test_blocked_on_validator_fail(monkeypatch):
    val = {"ea": "S6", "tested_at": "2026-06-01", "overall_verdict": "FAIL"}
    _wire(monkeypatch, coach=_good_coach(), validator=val)
    ok, _ = pg.can_go_live("S6")
    assert ok is False
