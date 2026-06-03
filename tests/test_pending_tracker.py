"""Tests for the stalled-agent detection logic.

evaluate_stalled() is pure (no filesystem) — we feed it a fake services list
and fake mtimes and assert exactly which agents are flagged.
"""
from scripts import pending_tracker as pt

NOW = 1_000_000.0

SERVICES = [
    {"id": "mtf", "name": "MTF", "profiles": ["vps"],
     "health": {"type": "file", "path": "a.json", "max_age": 600, "grace": 300}},
    {"id": "jtcc", "name": "JTCC", "profiles": ["vps"],
     "health": {"type": "file", "path": "b.json", "max_age": 300}},
    {"id": "coach", "name": "Coach", "profiles": ["vps"],
     "health": {"type": "process"}},
    {"id": "localonly", "name": "LocalOnly", "profiles": ["local"],
     "health": {"type": "file", "path": "c.json", "max_age": 100}},
]


def test_fresh_agents_not_stalled():
    mtimes = {"a.json": NOW - 100, "b.json": NOW - 100}
    assert pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps") == []


def test_stale_state_file_flagged():
    mtimes = {"a.json": NOW - 1000, "b.json": NOW - 100}  # a: 1000 > 900 -> stale
    out = pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps")
    assert [s["id"] for s in out] == ["mtf"]
    assert out[0]["age_s"] == 1000
    assert out[0]["threshold_s"] == 900


def test_grace_counts_toward_threshold():
    # mtf threshold = max_age 600 + grace 300 = 900; age 850 < 900 -> still fresh
    mtimes = {"a.json": NOW - 850, "b.json": NOW - 100}
    assert pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps") == []


def test_missing_state_file_is_stalled():
    mtimes = {"a.json": None, "b.json": NOW - 100}
    out = pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps")
    assert [s["id"] for s in out] == ["mtf"]
    assert out[0]["age_s"] is None
    assert "no state file" in out[0]["reason"]


def test_non_file_health_is_ignored():
    mtimes = {"a.json": NOW - 100, "b.json": NOW - 100}
    out = pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps")
    assert "coach" not in [s["id"] for s in out]  # process-health -> orchestrator's job


def test_profile_filter_respects_mode():
    mtimes = {"a.json": NOW - 100, "b.json": NOW - 100, "c.json": None}
    # vps mode: localonly (profile=local) is skipped despite a missing file
    assert "localonly" not in [s["id"] for s in pt.evaluate_stalled(SERVICES, mtimes, NOW, "vps")]
    # local mode: localonly IS checked -> flagged (missing file)
    assert "localonly" in [s["id"] for s in pt.evaluate_stalled(SERVICES, mtimes, NOW, "local")]
