"""Strategy Factory runner — the resumable stage dispatcher.

Each tick it loads every job and, for those with status RUNNING, calls the handler
for the job's current stage. Handlers are idempotent and advance the stage exactly
once on success, so a job survives restarts (resume = re-dispatch the same stage).
Gates park the job at WAITING_APPROVAL; the dashboard/Telegram advances it.

Managed as the `factory_runner` service. CLI: --once | --loop [--interval N].
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from trading_agents.factory import state as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("factory.runner")

HEARTBEAT = st.FACTORY_DIR / "_runner_state.json"
DEFAULT_INTERVAL = 45

# Autonomy: when FACTORY_AUTONOMOUS is truthy the plan + backtest gates self-approve
# on threshold (discovery → demo runs hands-free). GATE_LIVE (real money) is NEVER
# auto-approved — a human always approves the demo→real promotion.
AUTONOMOUS = os.getenv("FACTORY_AUTONOMOUS", "0").strip().lower() in ("1", "true", "yes", "on")
# Backtest must clear this to auto-advance to OPTIMIZE; below it the job is rejected.
AUTO_BACKTEST_MIN_PF = float(os.getenv("FACTORY_AUTO_BACKTEST_PF", "1.15"))
AUTO_BACKTEST_MIN_TRADES = int(os.getenv("FACTORY_AUTO_BACKTEST_TRADES", "10"))


# ── Telegram notify (best-effort) ─────────────────────────────────────────────

def _notify(category: str, msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents import telegram_hq
        telegram_hq.send(category, msg, level=level)
    except Exception:
        pass


def _load_spec(job: dict) -> dict:
    p = job.get("artifacts", {}).get("merged_spec")
    if p and Path(p).exists():
        return json.loads(Path(p).read_text(encoding="utf-8"))
    return {"name": job.get("source", {}).get("title", "strategy"),
            "symbols": ["XAUUSD"], "timeframe": "M3", "tunable_params": {}}


# ── Stage handlers ─────────────────────────────────────────────────────────────

def _h_ingest(job: dict) -> None:
    from trading_agents.factory import youtube as yt
    meta = yt.fetch_metadata(job["source"]["youtube_url"])
    job["source"].update({k: meta.get(k, job["source"].get(k))
                          for k in ("video_id", "title", "channel", "description", "duration_s")})
    st.advance(job, st.CLASSIFY, f"ingested: {job['source'].get('title','')[:60]}")


def _h_classify(job: dict) -> None:
    from trading_agents.factory import classify as clf
    res = clf.classify(job["source"])
    job["is_strategy"] = res["is_strategy"]
    job["classification_reason"] = res["reason"]
    if res["is_strategy"]:
        st.advance(job, st.RESEARCH_NB, f"strategy ({res['confidence']:.0%}): {res['reason'][:80]}")
        _notify("ceo", f"🏭 Factory {job['job_id']}: strategy detected — researching.\n{job['source'].get('title','')}")
    else:
        # Stash the suggested plan and pause for approval.
        art = st.artifact_dir(job["job_id"])
        plan = res.get("plan") or "Not a tradeable strategy. No build plan."
        (art / "build_plan.md").write_text(
            f"# Non-strategy video\n\n{res['reason']}\n\n## Suggested plan\n\n{plan}\n",
            encoding="utf-8")
        job["artifacts"]["build_plan"] = str(art / "build_plan.md")
        st.advance(job, st.GATE_PLAN, "non-strategy — plan ready")
        _notify("ceo", f"🏭 Factory {job['job_id']}: NOT a strategy — {res['reason']}. "
                       f"Review plan & approve/reject in dashboard /factory.", level="WARNING")


def _h_research_nb(job: dict) -> None:
    from trading_agents.factory import research
    research.run_notebook_research(job)
    st.advance(job, st.RESEARCH_VIDEO, "notebook research done")


def _h_research_video(job: dict) -> None:
    from trading_agents.factory import research
    research.run_video_research(job)
    st.advance(job, st.MERGE_SPEC, "video research done")


def _h_merge_spec(job: dict) -> None:
    from trading_agents.factory import spec as fspec
    fspec.merge_spec(job)
    st.advance(job, st.BUILD_PLAN, "spec merged")


def _h_build_plan(job: dict) -> None:
    from trading_agents.factory import spec as fspec
    fspec.build_plan(job, _load_spec(job))
    st.advance(job, st.GATE_PLAN, "build plan ready")


def _h_gate_plan(job: dict) -> None:
    ap = job["approvals"]["plan"]
    if ap["state"] == "approved":
        st.advance(job, st.CODEGEN, "plan approved")
    elif ap["state"] == "rejected":
        st.set_status(job, st.REJECTED, "plan rejected")
    elif AUTONOMOUS and job.get("is_strategy") is not False:
        # Auto-approve plan for real strategies; non-strategies still park for review.
        ap["state"] = "approved"
        ap["by"] = "autonomous"
        ap["at"] = st._now()
        st.advance(job, st.CODEGEN, "plan auto-approved (autonomous)")
    else:
        st.wait_for_gate(job, "plan", "awaiting plan approval (dashboard /factory)")
        _notify("ceo", f"🏭 Factory {job['job_id']}: build plan ready — approve in /factory.")


def _h_codegen(job: dict) -> None:
    if job.get("is_strategy") is False:
        st.set_status(job, st.DONE, "non-strategy: plan approved, nothing to build")
        return
    from trading_agents.factory import codegen
    res = codegen.generate_strategy(job, spec=_load_spec(job))
    if res.get("ok"):
        st.save_job(job)
        st.advance(job, st.BACKTEST, f"code generated: {res['strategy_id']} ({res.get('attempts')} attempts)")
    else:
        st.fail(job, f"codegen failed: {res.get('reason')}")
        _notify("dev_team", f"🏭 Factory {job['job_id']} codegen FAILED: {res.get('reason')}", level="WARNING")


def _h_backtest(job: dict) -> None:
    from trading_agents.scalp import backtest as bt
    sid = job["strategy_id"]
    if sid not in bt.STRATEGIES:
        bt.refresh_generated()  # codegen wrote it after this process imported backtest
    spec = _load_spec(job)
    symbol = (spec.get("symbols") or ["XAUUSD"])[0]
    if sid not in bt.STRATEGIES:
        st.fail(job, f"backtest: strategy {sid} not registered (generated load failed)")
        return
    tf = bt.STRATEGIES[sid][0]
    bars = bt._fetch_bars(symbol, tf, 5000)
    if not bars or not bars.get("close"):
        st.fail(job, f"backtest: no bars for {symbol} {tf}")
        return
    result = bt.backtest_one(sid, symbol, bars)
    art = st.artifact_dir(job["job_id"])
    (art / "backtest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    job["artifacts"]["backtest_report"] = str(art / "backtest.json")
    job["metrics"]["backtest"] = {k: result.get(k) for k in
                                  ("trades", "win_rate_pct", "profit_factor",
                                   "max_drawdown", "expectancy", "verdict")}
    st.advance(job, st.GATE_BACKTEST, f"backtest: PF={result.get('profit_factor')} "
               f"WR={result.get('win_rate_pct')}% trades={result.get('trades')}")


def _h_gate_backtest(job: dict) -> None:
    ap = job["approvals"]["backtest"]
    if ap["state"] == "approved":
        st.advance(job, st.OPTIMIZE, "backtest approved")
    elif ap["state"] == "rejected":
        st.set_status(job, st.REJECTED, "backtest rejected")
    elif AUTONOMOUS:
        # Threshold-based self-gate: clear the bar → optimize; below it → reject.
        m = job["metrics"]["backtest"]
        pf = m.get("profit_factor") or 0
        tr = m.get("trades") or 0
        if pf >= AUTO_BACKTEST_MIN_PF and tr >= AUTO_BACKTEST_MIN_TRADES:
            ap["state"] = "approved"
            ap["by"] = "autonomous"
            ap["at"] = st._now()
            st.advance(job, st.OPTIMIZE, f"backtest auto-approved (PF={pf} trades={tr})")
        else:
            st.set_status(job, st.REJECTED,
                          f"backtest auto-rejected (PF={pf} trades={tr} < bar "
                          f"{AUTO_BACKTEST_MIN_PF}/{AUTO_BACKTEST_MIN_TRADES})")
    else:
        st.wait_for_gate(job, "backtest", "awaiting backtest approval")
        m = job["metrics"]["backtest"]
        _notify("ceo", f"🏭 Factory {job['job_id']} {job['strategy_id']} backtest: "
                       f"PF={m.get('profit_factor')} WR={m.get('win_rate_pct')}% "
                       f"trades={m.get('trades')} ({m.get('verdict')}). Approve in /factory.")


def _h_optimize(job: dict) -> None:
    from trading_agents.factory import optimize as fopt, improve
    sid = job["strategy_id"]
    spec = _load_spec(job)
    opt = fopt.optimize_generic(sid, spec)
    if not opt.get("ok"):
        st.fail(job, f"optimize: {opt.get('reason')}")
        return
    full = opt["full"]
    job["metrics"]["optimize"] = {"full_pf": full.get("profit_factor"),
                                  "full_trades": full.get("trades"),
                                  "oos_pf": opt.get("oos_pf"),
                                  "config_path": opt.get("config_path")}
    job["artifacts"]["optimize_config"] = opt.get("config_path", "")
    st.save_job(job)

    if improve.should_soak(full, opt.get("oos_pf")) or improve.deployable(full):
        st.advance(job, st.DEMO_DEPLOY,
                   f"optimized PF={full.get('profit_factor')} — deploying to soak")
    else:
        res = improve.improve_via_code(job, spec, full)
        if res.get("ok"):
            st.advance(job, st.BACKTEST, f"improved (round {job['retries']['improve_code']}) — re-backtest")
        else:
            # Budget exhausted and still weak: deploy if not outright losing, else fail.
            if (full.get("profit_factor", 0) or 0) >= 1.0:
                st.advance(job, st.DEMO_DEPLOY, "below soak bar but >=1.0 PF — soak anyway")
            else:
                st.fail(job, f"unprofitable after improvement budget (PF={full.get('profit_factor')})")


def _h_demo_deploy(job: dict) -> None:
    from trading_agents.factory import paper_runner
    from trading_agents.scalp import backtest as bt
    sid = job["strategy_id"]
    if sid not in bt.STRATEGIES:
        bt.refresh_generated()
    spec = _load_spec(job)
    tf = bt.STRATEGIES[sid][0]
    syms = spec.get("symbols") or ["XAUUSD"]
    paper_runner.add_to_roster(job["job_id"], sid, tf, syms,
                               job["artifacts"].get("optimize_config", ""))
    st.advance(job, st.SOAK, f"deployed to demo soak ({sid} {tf} {syms})")
    _notify("ceo", f"🏭 Factory {job['job_id']} {sid} deployed to DEMO soak ({tf} {syms}). "
                   f"Tracking 1-3 weeks.")


def _h_soak(job: dict) -> None:
    from trading_agents.factory import improve
    from trading_agents.factory import paper_runner
    sid = job["strategy_id"]
    soak = {}
    if paper_runner.STATE_PATH.exists():
        try:
            state = json.loads(paper_runner.STATE_PATH.read_text(encoding="utf-8"))
            soak = state.get("strategies", {}).get(sid, {})
        except Exception:
            pass
    job["metrics"]["soak"] = soak
    ready, reasons = improve.ready_for_live(soak)
    if ready:
        st.advance(job, st.GATE_LIVE, f"soak passed: PF={soak.get('pf')} "
                   f"trades={soak.get('trades')} days={soak.get('days')}")
    else:
        # Stay at SOAK (re-checked next tick). Persist updated metrics only.
        st.save_job(job)


def _h_gate_live(job: dict) -> None:
    from trading_agents.factory import improve
    soak = job.get("metrics", {}).get("soak", {})
    ready, reasons = improve.ready_for_live(soak)
    ap = job["approvals"]["live"]
    if ap["state"] == "approved":
        if ready:
            st.set_status(job, st.DONE, "READY FOR REAL MONEY — human approved + soak gate pass")
            _notify("ceo", f"✅ Factory {job['job_id']} {job['strategy_id']} READY FOR REAL MONEY "
                           f"(PF={soak.get('pf')} trades={soak.get('trades')} days={soak.get('days')}). "
                           f"Wire into the live agent when you choose.")
        else:
            ap["state"] = "pending"  # fail-closed: metrics regressed since approval
            st.wait_for_gate(job, "live", f"approval held — soak gate fails: {reasons}")
    elif ap["state"] == "rejected":
        st.set_status(job, st.REJECTED, "go-live rejected")
    else:
        st.wait_for_gate(job, "live", f"awaiting real-money approval (gate {'PASS' if ready else 'PENDING'}: {reasons})")
        _notify("ceo", f"🏭 Factory {job['job_id']} {job['strategy_id']} soak {'PASSED' if ready else 'progress'} "
                       f"— PF={soak.get('pf')} trades={soak.get('trades')} days={soak.get('days')}. "
                       f"{'Approve real-money in /factory.' if ready else 'Still soaking: ' + str(reasons)}")


_HANDLERS = {
    st.INGEST: _h_ingest,
    st.CLASSIFY: _h_classify,
    st.RESEARCH_NB: _h_research_nb,
    st.RESEARCH_VIDEO: _h_research_video,
    st.MERGE_SPEC: _h_merge_spec,
    st.BUILD_PLAN: _h_build_plan,
    st.GATE_PLAN: _h_gate_plan,
    st.CODEGEN: _h_codegen,
    st.BACKTEST: _h_backtest,
    st.GATE_BACKTEST: _h_gate_backtest,
    st.OPTIMIZE: _h_optimize,
    st.DEMO_DEPLOY: _h_demo_deploy,
    st.SOAK: _h_soak,
    st.GATE_LIVE: _h_gate_live,
}


def process_job(job: dict) -> None:
    stage = job.get("stage")
    handler = _HANDLERS.get(stage)
    if handler is None:
        return
    try:
        handler(job)
    except Exception as e:  # noqa: BLE001
        log.exception("handler %s failed for %s", stage, job.get("job_id"))
        st.fail(job, f"{stage} error: {e}")


def tick() -> dict:
    counts: dict[str, int] = {}
    for summary in st.list_jobs():
        job = st.load_job(summary["job_id"])
        if job is None:
            continue
        status = job.get("status")
        counts[status] = counts.get(status, 0) + 1
        if status == st.RUNNING:
            log.info("[%s] stage=%s", job["job_id"], job["stage"])
            process_job(job)
    return counts


def _heartbeat(counts: dict) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pid": os.getpid(), "counts": counts,
    }, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    args = ap.parse_args()

    if args.once or not args.loop:
        counts = tick()
        _heartbeat(counts)
        log.info("tick done: %s", counts)
        return
    log.info("Factory runner loop (interval=%ds)", args.interval)
    while True:
        try:
            counts = tick()
            _heartbeat(counts)
        except Exception as e:  # noqa: BLE001
            log.error("runner tick error: %s", e)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
