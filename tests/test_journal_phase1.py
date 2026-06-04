"""
Phase 1 keystone tests for the trade journal + close-reconciler contract.

The bug that made every downstream number wrong was the journal's full-file
rewrite under concurrent writers. These tests lock in the append-only guarantees:
  1. concurrency no-clobber — many processes append, zero records lost
  2. close idempotency — closing twice never double-writes / double-counts
  3. attribution — strategies sharing one magic keep distinct strategies[]
  4. fold / stats correctness — demo filter, by_agent, sample_ok

Run:  python -m pytest tests/test_journal_phase1.py -q
  or: python tests/test_journal_phase1.py     (self-runs without pytest)
"""
from __future__ import annotations

import importlib
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def _fresh_journal(d: str):
    """Import a fresh trade_journal bound to temp dir `d` (sharded storage)."""
    os.environ["TRADE_JOURNAL_DIR"] = str(Path(d) / "journal")
    os.environ["TRADE_JOURNAL_PATH"] = str(Path(d) / "legacy.jsonl")
    sys.modules.pop("trading_agents.trade_journal", None)
    return importlib.import_module("trading_agents.trade_journal")


# ── worker for the concurrency test (must be top-level for spawn) ──────────────
def _worker_open(d: str, agent: str, base: int, count: int) -> None:
    tj = _fresh_journal(d)
    for i in range(count):
        tk = base + i
        tj.open_trade(tk, "EURUSD", "BUY", 1.10, 1.09, 1.12, 0.1,
                      source=agent, strategies=[f"{agent}_strat"], agent=agent)


def test_concurrency_no_clobber():
    """N processes each append M opens concurrently. Per-writer sharding +
    append-only must lose zero records (the old full-rewrite lost them)."""
    d = tempfile.mkdtemp()
    N, M = 6, 50
    procs = [mp.Process(target=_worker_open, args=(d, f"agent{n}", n * 1000, M))
             for n in range(N)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    tj = _fresh_journal(d)
    opens = tj.get_open_tickets()
    assert len(opens) == N * M, f"lost records: got {len(opens)} expected {N * M}"
    print(f"  [ok] concurrency: {N}x{M}={N*M} opens, none lost")


def test_close_idempotency():
    d = tempfile.mkdtemp()
    tj = _fresh_journal(d)
    tj.open_trade(1, "EURUSD", "BUY", 1.10, 1.09, 1.12, 0.1, source="MTF", agent="mtf")
    assert tj.close_trade(1, 1.12, 20.0, "TP_HIT") is True
    assert tj.close_trade(1, 1.12, 20.0, "TP_HIT") is False, "second close must be no-op"
    s = tj.get_stats()
    assert s["total"]["trades"] == 1, "double-counted a close"
    assert s["total"]["net_pnl"] == 20.0
    print("  [ok] idempotency: double-close counted once")


def test_shared_magic_distinct_strategies():
    """Two scalp strategies share magic 20260522 but must keep distinct strategies[]."""
    d = tempfile.mkdtemp()
    tj = _fresh_journal(d)
    tj.open_trade(10, "XAUUSD", "BUY", 2000, 1990, 2020, 0.1, source="Scalp", strategies=["GS11"], agent="scalp")
    tj.open_trade(11, "XAUUSD", "SELL", 2000, 2010, 1980, 0.1, source="Scalp", strategies=["GS07"], agent="scalp")
    tj.close_trade(10, 2020, 30.0, "TP_HIT")
    tj.close_trade(11, 2010, -10.0, "SL_HIT")
    s = tj.get_stats()
    assert s["by_strategy"]["GS11"]["net_pnl"] == 30.0
    assert s["by_strategy"]["GS07"]["net_pnl"] == -10.0
    assert s["by_agent"]["scalp"]["trades"] == 2
    print("  [ok] attribution: shared-magic strategies stay distinct")


def test_demo_filter_and_sample():
    d = tempfile.mkdtemp()
    tj = _fresh_journal(d)
    tj.open_trade(20, "EURUSD", "BUY", 1.1, 1.09, 1.12, 0.1, source="MTF", agent="mtf")
    tj.open_trade(21, "EURUSD", "BUY", 1.1, 1.09, 1.12, 0.1, source="MTF", agent="mtf")
    tj.close_trade(20, 1.12, 10.0, "TP_HIT", demo=True)
    tj.close_trade(21, 1.09, -5.0, "SL_HIT", demo=False)
    assert tj.get_stats(demo=True)["total"]["net_pnl"] == 10.0
    assert tj.get_stats(demo=False)["total"]["net_pnl"] == -5.0
    assert tj.get_stats()["total"]["sample_ok"] is False, "n<20 must flag insufficient"
    print("  [ok] demo filter + sample_ok")


def test_orphan_close_does_not_crash_stats():
    """A close event with no matching open (orphan) must not crash get_stats."""
    d = tempfile.mkdtemp()
    tj = _fresh_journal(d)
    # close a ticket that was never opened
    tj.close_trade(999, 1.10, 5.0, "CLOSED", demo=True)
    s = tj.get_stats()  # must not raise
    assert s["total"]["trades"] == 1
    assert "unknown" in s["by_symbol"]
    print("  [ok] orphan close handled (no crash)")


def _main():
    for fn in (test_concurrency_no_clobber, test_close_idempotency,
               test_shared_magic_distinct_strategies, test_demo_filter_and_sample,
               test_orphan_close_does_not_crash_stats):
        fn()
    print("ALL PHASE-1 JOURNAL TESTS PASSED")


if __name__ == "__main__":
    mp.freeze_support()
    _main()
