"""
JTCC — Junait Trading Command Center
Main asyncio event loop orchestrating all 4 layers.

Usage:
  python -m trading_agents.jtcc.main
  python -m trading_agents.jtcc.main --dry-run
  python -m trading_agents.jtcc.main --symbol XAUUSD --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent.parent
LOG_DIR = BASE_DIR / "logs" / "jtcc"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "jtcc.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("jtcc.main")
BD_TZ = ZoneInfo("Asia/Dhaka")

# State file for dashboard
STATE_FILE = LOG_DIR / "_jtcc_state.json"


def _load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class JTCC:
    def __init__(self, config: dict, dry_run: bool = False, symbols: list[str] | None = None) -> None:
        self.config = config
        self.dry_run = dry_run
        self.symbols = symbols or config.get("symbols", ["XAUUSD"])
        self._running = False
        self._state: dict = {
            "status": "starting",
            "dry_run": dry_run,
            "symbols": self.symbols,
            "confluence": {},
            "last_signals": [],
            "daily_api_calls": 0,
            "started_at": datetime.now(tz=BD_TZ).isoformat(),
        }

        from trading_agents.jtcc.core.market_feed import MarketFeed
        from trading_agents.jtcc.agents.momentum_agent import MomentumAgent
        from trading_agents.jtcc.agents.session_agent import SessionAgent
        from trading_agents.jtcc.agents.news_guard import NewsGuardAgent
        from trading_agents.jtcc.agents.market_structure import MarketStructureAgent
        from trading_agents.jtcc.agents.smc_ict_agent import SmcIctAgent
        from trading_agents.jtcc.agents.master_agent import MasterAgent
        from trading_agents.jtcc.agents.ict_specialist import ICTSpecialist
        from trading_agents.jtcc.strategies.loader import StrategyLoader
        from trading_agents.jtcc.strategies.rule_engine import RuleEngine
        from trading_agents.jtcc.execution.risk_manager import check_daily_dd, can_trade, emergency_close_all
        from trading_agents.jtcc.execution.mt5_client import place_trade, ping

        master_cfg = config.get("master_agent", {})
        self.feed = MarketFeed(
            symbols=self.symbols,
            poll_interval_s=config.get("mt5_bridge", {}).get("poll_interval_s", 1.0),
            bar_timeframe=config.get("timeframes", {}).get("primary", "5min"),
        )
        self.l1_agents = [
            MomentumAgent(),
            SessionAgent(),
            NewsGuardAgent(
                block_before=config.get("news", {}).get("block_before_mins", 30),
                block_after=config.get("news", {}).get("block_after_mins", 15),
            ),
            MarketStructureAgent(),
            SmcIctAgent(),
        ]
        self.master = MasterAgent(
            min_strategies=master_cfg.get("min_strategies_required", 3),
            min_confidence=master_cfg.get("min_confluence_score", 6.0),
            model=master_cfg.get("model", "claude-opus-4-8"),
            max_tokens=master_cfg.get("max_tokens", 600),
            nvidia_tier=master_cfg.get("nvidia_tier", "HEAVY"),
            alert_on_fallback=master_cfg.get("alert_on_fallback", True),
            alert_cooldown_min=master_cfg.get("fallback_alert_cooldown_min", 15),
        )
        # ICT 2022 LLM specialist — votes alongside YAML strategies on M15
        ict_cfg = config.get("ict_specialist", {})
        self.ict_specialist = ICTSpecialist(
            model=ict_cfg.get("model", master_cfg.get("model", "claude-opus-4-8")),
            nvidia_tier=ict_cfg.get("nvidia_tier", "HEAVY"),
            max_calls_per_day=ict_cfg.get("max_calls_per_day", 30),
            max_tokens=ict_cfg.get("max_tokens", 400),
            symbols=ict_cfg.get("symbols", ["XAUUSD", "EURUSD", "GBPUSD"]),
        )
        self.loader = StrategyLoader()
        self.rule_engine = RuleEngine()
        self._check_daily_dd = check_daily_dd
        self._can_trade = can_trade
        self._emergency_close = emergency_close_all
        self._place_trade = place_trade
        self._ping_mt5 = ping

    async def _on_bar_close(self, symbol: str, timeframe: str, ohlcv: dict, risk: dict) -> None:
        """Called when a new bar closes. Runs full L1→L2→L3 pipeline."""
        from trading_agents.jtcc.core.latency_tracker import tracker
        t0 = time.perf_counter()
        log.debug("Bar close: %s %s", symbol, timeframe)

        # Build MarketContext (L1)
        from trading_agents.jtcc.core.market_context import build_context
        price = {"bid": ohlcv["close"][-1] * 0.9998, "ask": ohlcv["close"][-1] * 1.0002,
                 "spread": ohlcv["close"][-1] * 0.0004, "mid": ohlcv["close"][-1]}
        with tracker.measure("l1_full"):
            ctx_obj = await build_context(symbol, price, ohlcv, risk, self.l1_agents)
        ctx_dict = ctx_obj.to_dict()

        # ── Academic analytics layer: TSMOM (Moskowitz 2012) + Pairs (Gatev 2006) ──
        # Refresh full multi-symbol analytics every cycle (cheap), then attach
        # this symbol's view to context for rule engine consumption.
        with tracker.measure("l_analytics"):
            from trading_agents.jtcc.analytics.hub import hub as analytics_hub
            bars_by_symbol = {s: self.feed.get_bars(s) for s in self.symbols
                              if self.feed.get_bars(s)}
            analytics_hub.compute_all(bars_by_symbol)
            ctx_dict["analytics"] = analytics_hub.for_symbol(symbol)

        # ── MTF analytics layer for M3 scalping strategies (S17-S21) ──
        # Fetches D1/H4/H1/M15/M3 bars + computes intraday signals (VWAP,
        # session ranges, NR7). Cached per-TF — minimal overhead.
        with tracker.measure("l_mtf"):
            from trading_agents.jtcc.analytics.mtf import hub_mtf
            from trading_agents.jtcc.analytics.intraday_signals import get_all_intraday_signals
            ctx_dict["mtf"] = hub_mtf.for_symbol(symbol)
            ctx_dict["intraday"] = get_all_intraday_signals()

        # L2: Run all strategy agents in parallel
        strategies = self.loader.all()
        if not strategies:
            return

        with tracker.measure("l2_strategy_eval"):
            votes = [self.rule_engine.evaluate(s, ctx_dict) for s in strategies]
        # ICT 2022 LLM specialist — adds an additional vote (smart pre-gated)
        with tracker.measure("l2_ict_specialist"):
            ict_vote = await self.ict_specialist.vote(ctx_dict)
        votes.append(ict_vote)
        active_votes = [v for v in votes if v["signal"] != "NONE"]
        self._state["ict_specialist_stats"] = self.ict_specialist.stats()

        # Update confluence state for dashboard
        buy_v = [v for v in active_votes if v["signal"] == "BUY"]
        sell_v = [v for v in active_votes if v["signal"] == "SELL"]
        self._state["confluence"][symbol] = {
            "buy_count": len(buy_v),
            "sell_count": len(sell_v),
            "buy_strategies": [v["strategy"] for v in buy_v],
            "sell_strategies": [v["strategy"] for v in sell_v],
            "session": ctx_dict.get("session", {}).get("name"),
            "trend": ctx_dict.get("market", {}).get("trend"),
            "news_blocked": ctx_dict.get("news", {}).get("blocked"),
            "updated_at": datetime.now(tz=BD_TZ).isoformat(),
        }
        self._save_state()

        # Check if enough votes to trigger L3
        max_votes = max(len(buy_v), len(sell_v))
        if max_votes < self.master.min_strategies:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug("L2: %d votes for %s — below threshold (%dms)", max_votes, symbol, elapsed)
            return

        # L3: Master Decision Agent (1 Claude API call)
        log.info("Signal candidate: %s — %dB/%dS votes. Calling Master Agent...",
                 symbol, len(buy_v), len(sell_v))
        with tracker.measure("l3_master"):
            decision = await self.master.decide(ctx_dict, active_votes)
        self._state["daily_api_calls"] = self.master.daily_calls
        self._state["backend_stats"] = self.master.backend_stats()

        if not decision.get("execute") or decision.get("decision") == "WAIT":
            log.info("Master: %s — %s", symbol, decision.get("rationale", "WAIT"))
            return

        # L4: Execute trade
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("SIGNAL: %s %s conf=%.1f (%.0fms) strategies=%s",
                 decision["decision"], symbol, decision.get("confidence", 0),
                 elapsed, decision.get("strategies_agreed", []))

        await self._execute_trade(decision, ctx_dict)

    async def _on_tick(self, symbol: str, price: dict, risk: dict, raw_state: dict) -> None:
        """Called on each price tick. Updates heartbeat + DD check."""
        # Heartbeat: refresh state file so Guardian knows we're alive
        # (bars only close every 5min, but state must update more often)
        self._state["last_heartbeat"] = datetime.now(tz=BD_TZ).isoformat()
        self._state["last_tick_symbol"] = symbol
        if "ticks_processed" not in self._state:
            self._state["ticks_processed"] = 0
        self._state["ticks_processed"] += 1
        # Save every ~30 ticks (~30 seconds at 1s poll) to avoid disk thrash
        if self._state["ticks_processed"] % 30 == 0:
            self._save_state()

        # Daily DD check on every tick
        shutdown, dd_pct = self._check_daily_dd()
        if shutdown:
            log.critical("DAILY DD SHUTDOWN: %.1f%% — EMERGENCY CLOSE ALL", dd_pct)
            self._emergency_close(f"Daily DD {dd_pct:.1f}% >= 6%")
            self._running = False

    async def _execute_trade(self, decision: dict, ctx_dict: dict) -> None:
        from trading_agents.jtcc.execution.risk_manager import calculate_lot, check_spread
        from trading_agents.jtcc.monitoring.performance_tracker import log_signal, log_trade_open

        symbol = decision["symbol"]
        action = decision["decision"]
        entry = decision.get("entry_price", 0)
        sl = decision.get("stop_loss", 0)
        tp = decision.get("take_profit", 0)
        spread = ctx_dict.get("price", {}).get("spread", 0)

        # Spread check
        spread_ok, spread_msg = check_spread(symbol, entry, sl, spread)
        if not spread_ok:
            log.warning("Spread check failed: %s", spread_msg)
            return

        # Calculate lot size — use TSMOM vol scalar if available
        tsmom_scalar = ctx_dict.get("analytics", {}).get("tsmom", {}).get("position_scalar", 1.0)
        lot, lot_info = calculate_lot(symbol, entry, sl, vol_scalar=tsmom_scalar)
        if lot <= 0:
            log.warning("Lot calc failed: %s", lot_info)
            return

        log_signal(decision)

        if self.dry_run:
            log.info("[DRY RUN] Would place: %s %s %.2f lots SL=%.5f TP=%.5f",
                     action, symbol, lot, sl, tp)
            self._notify_signal(decision, lot, dry_run=True)
            return

        # Place trade
        strategies = ",".join(decision.get("strategies_agreed", [])[:2])
        result = self._place_trade(
            symbol=symbol, action=action, lot=lot, sl=sl, tp=tp,
            magic=20260600, comment="JTCC", strategy=strategies,
        )

        if result.get("success") or result.get("ticket"):
            log_trade_open(result, decision)
            try:
                from trading_agents.trade_journal import open_trade as _jopen
                _jopen(
                    ticket=int(result.get("ticket", 0)),
                    symbol=symbol,
                    direction=action,
                    entry_price=entry,
                    sl=sl,
                    tp=tp,
                    volume=lot,
                    source="JTCC",
                    strategies=decision.get("strategies_agreed", []),
                    agent="jtcc_master",
                    backend=decision.get("backend", ""),
                    confluence_score=float(decision.get("confluence_score", 0)),
                    rationale=decision.get("rationale", ""),
                )
            except Exception:
                pass
            self._notify_signal(decision, lot, dry_run=False)
            self._state["last_signals"].append({
                **decision, "lot": lot, "ticket": result.get("ticket"),
                "ts": datetime.now(tz=BD_TZ).isoformat(),
            })
            self._state["last_signals"] = self._state["last_signals"][-20:]
            self._save_state()

            # ── Paper-faithful pair execution (Gatev 2006): dollar-neutral ──
            # If this trade was triggered by a Pairs YAML, also place the opposite
            # leg on the paired symbol so the position is truly market-neutral.
            await self._maybe_place_pair_leg(decision, ctx_dict, result.get("ticket"))
        else:
            log.error("Trade placement failed: %s", result.get("error", result))

    async def _maybe_place_pair_leg(self, decision: dict, ctx_dict: dict, primary_ticket) -> None:
        """If decision came from a Pairs strategy, also place the opposite leg."""
        strategies_agreed = [s for s in decision.get("strategies_agreed", []) if "Pairs" in s]
        if not strategies_agreed:
            return  # not a pair trade

        from trading_agents.jtcc.analytics.hub import PAIRS_CONFIG
        symbol = decision.get("symbol")
        direction = decision.get("decision")
        opposite_dir = "SELL" if direction == "BUY" else "BUY"

        # Find which configured pair this symbol belongs to
        partner_symbol = None
        for p in PAIRS_CONFIG:
            if p["a"] == symbol:
                partner_symbol = p["b"]
                break
            if p["b"] == symbol:
                partner_symbol = p["a"]
                break
        if not partner_symbol:
            return

        # Fetch live tick for partner to compute entry/sl/tp
        try:
            from trading_agents.jtcc.execution.mt5_client import _request
            tick = await asyncio.to_thread(_request, "GET", f"/tick/{partner_symbol}")
            partner_price = tick.get("bid" if opposite_dir == "SELL" else "ask")
            if not partner_price:
                log.warning("Pair leg: no tick for %s", partner_symbol)
                return

            # Use ATR-based SL/TP (1:1 RR, dollar-neutral pair logic)
            partner_bars = self.feed.get_bars(partner_symbol) or {}
            partner_closes = partner_bars.get("close", [])
            if len(partner_closes) < 14:
                log.warning("Pair leg: insufficient bars for %s", partner_symbol)
                return
            # Simple ATR proxy: last 14 close range
            atr_proxy = (max(partner_closes[-14:]) - min(partner_closes[-14:])) / 14
            sl_dist = atr_proxy * 1.5
            if opposite_dir == "BUY":
                partner_sl = round(partner_price - sl_dist, 5)
                partner_tp = round(partner_price + sl_dist * 1.5, 5)
            else:
                partner_sl = round(partner_price + sl_dist, 5)
                partner_tp = round(partner_price - sl_dist * 1.5, 5)

            from trading_agents.jtcc.execution.risk_manager import calculate_lot
            partner_lot, partner_info = calculate_lot(partner_symbol, partner_price, partner_sl)
            if partner_lot <= 0:
                log.warning("Pair leg lot calc failed: %s", partner_info)
                return

            log.info("PAIR LEG: %s %s %.2f lots (paired with primary ticket %s)",
                     opposite_dir, partner_symbol, partner_lot, primary_ticket)

            partner_result = await asyncio.to_thread(
                self._place_trade,
                symbol=partner_symbol, action=opposite_dir, lot=partner_lot,
                sl=partner_sl, tp=partner_tp,
                magic=20260600, comment=f"PAIR:{primary_ticket}",
                strategy=strategies_agreed[0][:20],
            )
            if partner_result.get("success") or partner_result.get("ticket"):
                log.info("Pair leg placed: %s ticket %s",
                         partner_symbol, partner_result.get("ticket"))
                # Notify Telegram about the second leg
                try:
                    from trading_agents.telegram_hq import send as tg_send
                    tg_send("live_trading",
                            f"⚖️ JTCC PAIR LEG\n{opposite_dir} {partner_symbol} {partner_lot:.2f} lots\n"
                            f"Paired with primary ticket {primary_ticket}\n"
                            f"Strategy: {strategies_agreed[0]}",
                            level="INFO", title=f"Pair Leg {partner_symbol}")
                except Exception:
                    pass
            else:
                log.error("Pair leg placement failed: %s", partner_result.get("error"))
        except Exception as e:
            log.error("Pair leg execution error: %s", e)

    def _notify_signal(self, decision: dict, lot: float, dry_run: bool = False) -> None:
        try:
            from trading_agents.telegram_hq import send as tg_send
            dr = " [DRY RUN]" if dry_run else ""
            symbol = decision["symbol"]
            direction = decision["decision"]
            conf = decision.get("confidence", 0)
            entry = decision.get("entry_price", 0)
            sl = decision.get("stop_loss", 0)
            tp = decision.get("take_profit", 0)
            rr = decision.get("rr_ratio", 0)
            strategies = ", ".join(decision.get("strategies_agreed", []))
            msg = (
                f"🎯 JTCC SIGNAL{dr}\n"
                f"{direction} {symbol} | Conf: {conf}/10\n"
                f"Entry: {entry:.5f} | SL: {sl:.5f} | TP: {tp:.5f}\n"
                f"RR: 1:{rr:.1f} | Lot: {lot:.2f}\n"
                f"Strategies: {strategies}\n"
                f"Rationale: {decision.get('rationale', '')[:150]}"
            )
            tg_send("live_trading", msg, level="INFO", title=f"JTCC {direction} {symbol}")
        except Exception as e:
            log.debug("Signal notify failed: %s", e)

    def _save_state(self) -> None:
        try:
            STATE_FILE.write_text(
                json.dumps(self._state, indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            pass

    async def run(self) -> None:
        self._running = True
        log.info("JTCC starting — symbols=%s dry_run=%s", self.symbols, self.dry_run)
        log.info("Strategies loaded: %d (%s)", self.loader.count(), self.loader.names())

        # Start strategy hot-reloader
        self.loader.start_watcher(
            interval_s=self.config.get("strategies", {}).get("hot_reload_interval_s", 5)
        )

        # Wire feed events
        self.feed.on_bar_close(self._on_bar_close)
        self.feed.on_tick(self._on_tick)

        # MT5 bridge connectivity check
        if not self.dry_run:
            ok = await asyncio.to_thread(self._ping_mt5)
            if ok:
                log.info("MT5 bridge: connected")
            else:
                log.warning("MT5 bridge: unreachable — trades will be disabled until connected")

        self._state["status"] = "running"
        self._save_state()

        # Notify startup
        try:
            from trading_agents.telegram_hq import send as tg_send
            mode = "DRY RUN" if self.dry_run else "LIVE"
            tg_send("live_trading",
                    f"🤖 JTCC started ({mode}) | {len(self.symbols)} symbols | {self.loader.count()} strategies",
                    level="INFO", title="JTCC Online")
        except Exception:
            pass

        try:
            await self.feed.start()
        except asyncio.CancelledError:
            pass
        finally:
            self._state["status"] = "stopped"
            self._save_state()
            log.info("JTCC stopped.")

    def stop(self) -> None:
        self._running = False
        self.feed.stop()


async def _main(args: argparse.Namespace) -> None:
    config = _load_config()
    symbols = [args.symbol] if args.symbol else config.get("symbols", ["XAUUSD"])
    jtcc = JTCC(config=config, dry_run=args.dry_run, symbols=symbols)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, jtcc.stop)
        except (NotImplementedError, OSError):
            pass  # Windows

    await jtcc.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="JTCC — Junait Trading Command Center")
    parser.add_argument("--dry-run", action="store_true", help="Simulate signals, no real trades")
    parser.add_argument("--symbol", help="Single symbol to analyze (default: all from config)")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
