"""Autonomous strategy code generation + smoke validation.

The riskiest part of the factory: an LLM writes a Python strategy function that
is then exec'd and trusted to trade. Safety is layered:
  - generate_strategy() prompts the LLM to use ONLY the indicators.py catalog,
    writes the candidate to trading_agents/scalp/generated/, then
  - AST allow-list validation (generated_loader.validate_source), then
  - a process-isolated smoke test on SYNTHETIC bars (no bridge needed): the
    function must import, run without throwing, fire a sane number of signals,
    and produce non-inverted SL/TP. Failure feeds the error back to the LLM and
    retries (default 4).

CLI: python -m trading_agents.factory.codegen --smoke <file.py> [symbol]
     -> prints JSON {ok, reason, metrics}; used for subprocess isolation.
"""
from __future__ import annotations

import argparse
import inspect
import json
import logging
import math
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from trading_agents.factory import generated_loader as gl
from trading_agents.factory import state as st

log = logging.getLogger("factory.codegen")

GENERATED_DIR = BASE_DIR / "trading_agents" / "scalp" / "generated"
MAX_RETRIES = 4
SMOKE_BARS = 700
SMOKE_TIMEOUT_S = 40


# ── LLM client ────────────────────────────────────────────────────────────────

def _make_client():
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None  # chat_resilient falls through to claude CLI / NVIDIA


def _indicator_catalog_text() -> str:
    """Exact signatures of the allowed indicator functions, for the prompt."""
    from trading_agents.scalp import indicators as ind
    lines = []
    for name in sorted(gl.INDICATOR_CATALOG):
        fn = getattr(ind, name, None)
        if fn is None or not callable(fn):
            continue
        try:
            sig = str(inspect.signature(fn))
        except (ValueError, TypeError):
            sig = "(...)"
        doc = (inspect.getdoc(fn) or "").split("\n")[0]
        lines.append(f"  {name}{sig}" + (f"  # {doc}" if doc else ""))
    return "\n".join(lines)


# ── Prompt ─────────────────────────────────────────────────────────────────────

_EXAMPLE = '''\
from trading_agents.scalp.indicators import ema, atr, rsi, session_info

GS_PARAMS = {"rr": 2.0, "rsi_os": 30.0, "sl_atr": 1.5}

def _gs50_example(bars, t_i, spread, symbol="XAUUSD"):
    c = bars.get("close", []); h = bars.get("high", []); l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 60:
        return None
    cl = c[:t_i + 1]; hl = h[:t_i + 1]; ll = l[:t_i + 1]
    if not session_info(times[t_i])["any_primary"]:
        return None
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None
    price = cl[-1]
    if ema(cl, 9) > ema(cl, 50) and rsi(cl, 14) < GS_PARAMS["rsi_os"]:
        sl = price - GS_PARAMS["sl_atr"] * atr_val
        return {"signal": "BUY", "sl": sl, "tp": price + GS_PARAMS["rr"] * (price - sl)}
    return None

STRATEGY_ID = "GS50"
TIMEFRAME = "M3"
SYMBOLS = ["XAUUSD"]
STRATEGY_FN = _gs50_example
'''


def _system_prompt() -> str:
    return f"""You write ONE Python trading-strategy module for a backtest engine.

HARD RULES (a static validator rejects violations):
- Import ONLY from these (nothing else, no os/sys/json/open/eval/exec):
    from trading_agents.scalp.indicators import <names>
    import math            # allowed
    from __future__ import annotations   # allowed
- You may ONLY call these indicator functions:
{_indicator_catalog_text()}
- No classes, no async, no file/network/IO, no dunder attributes.

THE FUNCTION CONTRACT:
    def _gsNN_slug(bars, t_i, spread, symbol="XAUUSD") -> dict | None
- bars is a dict of equal-length lists: "open","high","low","close","time"(unix s),"volume".
- t_i is the current bar index. Slice inclusive: cl = bars["close"][:t_i+1]. Use only data up to t_i (no lookahead).
- Return {{"signal":"BUY"|"SELL", "sl":float, "tp":float}} or None.
- SL/TP must be on the correct side of entry (BUY: sl < price < tp; SELL: tp < price < sl), else the engine rejects the trade.
- Guard early bars (if t_i < 60: return None) and atr<=0.
- Put tunable numbers in a module-level dict named <SID>_PARAMS so the optimizer can sweep them.

THE MODULE MUST END WITH these four module-level names:
    STRATEGY_ID = "GSNN"      # given to you
    TIMEFRAME   = "M1"|"M3"|"M5"|"M15"
    SYMBOLS     = ["XAUUSD", ...]
    STRATEGY_FN = _gsNN_slug

Output ONLY the Python module in a single ```python code block. No prose.

EXAMPLE (structure to follow):
```python
{_EXAMPLE}```"""


def _user_prompt(spec: dict, strategy_id: str, prev_code: str = "",
                 prev_error: str = "") -> str:
    parts = [
        f"STRATEGY_ID to use: {strategy_id}",
        "Strategy spec (translate these rules into the function):",
        json.dumps(spec, indent=2, ensure_ascii=False)[:8000],
    ]
    if prev_code:
        parts += [
            "\nYour previous attempt FAILED validation/smoke-test. Fix it.",
            "Previous code:", "```python", prev_code[:6000], "```",
            "Error:", prev_error[:1500],
        ]
    return "\n".join(parts)


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def _slug(spec: dict) -> str:
    name = (spec.get("name") or spec.get("strategy_name") or "strategy").lower()
    s = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return (s or "strategy")[:32]


# ── Synthetic bars for the smoke test (no bridge needed) ──────────────────────

def _synth_bars(n: int = SMOKE_BARS, symbol: str = "XAUUSD", seed: int = 7) -> dict:
    rnd = random.Random(seed)
    px = 2000.0 if symbol == "XAUUSD" else 1.10
    step = px * 0.0012
    o, h, l, c, t, v = [], [], [], [], [], []
    ts = 1_700_000_000
    drift = 0.0
    for i in range(n):
        if i % 80 == 0:
            drift = rnd.uniform(-0.4, 0.4) * step  # regime shifts -> swings
        op = px
        px += drift + rnd.uniform(-step, step)
        hi = max(op, px) + abs(rnd.uniform(0, step))
        lo = min(op, px) - abs(rnd.uniform(0, step))
        o.append(round(op, 5)); h.append(round(hi, 5)); l.append(round(lo, 5))
        c.append(round(px, 5)); t.append(ts + i * 180); v.append(rnd.randint(50, 500))
    return {"open": o, "high": h, "low": l, "close": c, "time": t, "volume": v}


def smoke_test_file(path: Path, symbol: str = "XAUUSD") -> dict:
    """Import + run a generated strategy on several synthetic regimes. Returns
    {ok, reason, metrics}. In-process; the CLI wraps this in a subprocess.

    The smoke test is a SAFETY/SANITY gate, not a profitability gate: it catches
    crashes, fire-on-every-bar, and inverted SL/TP. A selective strategy that
    produces 0 signals on synthetic random walks is a SOFT pass — the real
    BACKTEST stage (on live bars) judges whether it trades enough.
    """
    try:
        mod = gl.load_module(Path(path))
        sid, tf, syms, fn = gl._extract(mod)
    except Exception as e:
        return {"ok": False, "reason": f"load/validate: {e}", "metrics": {}}

    sym = symbol if symbol in syms else (syms[0] if syms else symbol)
    wants_symbol = "symbol" in inspect.signature(fn).parameters

    tot_sig = tot_err = tot_inv = tot_eval = 0
    err_sample = ""
    max_fire_ratio = 0.0
    for seed in (7, 19, 101):  # up-drift, down-drift, choppy via different seeds
        bars = _synth_bars(symbol=sym, seed=seed)
        n = len(bars["close"])
        sig_n = 0
        for i in range(60, n - 1):
            try:
                sig = fn(bars, i, 0.0001, sym) if wants_symbol else fn(bars, i, 0.0001)
            except Exception as e:
                tot_err += 1
                if not err_sample:
                    err_sample = f"{type(e).__name__}: {e}"
                continue
            if not sig or sig.get("signal") not in ("BUY", "SELL"):
                continue
            price = bars["close"][i]
            sl, tp = sig.get("sl"), sig.get("tp")
            if not (isinstance(sl, (int, float)) and isinstance(tp, (int, float))) or sl <= 0 or tp <= 0:
                tot_inv += 1
                continue
            if sig["signal"] == "BUY" and not (sl < price < tp):
                tot_inv += 1
            elif sig["signal"] == "SELL" and not (tp < price < sl):
                tot_inv += 1
            else:
                sig_n += 1
        ev = n - 61
        tot_sig += sig_n
        tot_eval += ev
        max_fire_ratio = max(max_fire_ratio, sig_n / ev if ev else 0.0)

    metrics = {"signals": tot_sig, "errors": tot_err, "inverted": tot_inv,
               "evaluated": tot_eval, "max_fire_ratio": round(max_fire_ratio, 3)}
    # Hard safety gates
    if tot_err > tot_eval * 0.02:
        return {"ok": False, "reason": f"too many exceptions ({tot_err}) e.g. {err_sample}",
                "metrics": metrics}
    if max_fire_ratio > 0.5:
        return {"ok": False, "reason": f"fires on >50% of bars ({max_fire_ratio:.0%}) — no real condition",
                "metrics": metrics}
    if tot_inv > max(5, tot_sig):
        return {"ok": False, "reason": f"{tot_inv} inverted/bad SL-TP vs {tot_sig} good",
                "metrics": metrics}
    note = "smoke ok" if tot_sig else "smoke ok (0 signals on synthetic; backtest judges selectivity)"
    return {"ok": True, "reason": note, "metrics": metrics}


def run_smoke_subprocess(path: Path, symbol: str = "XAUUSD") -> dict:
    """Run smoke_test_file in an isolated child process (hard timeout)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "trading_agents.factory.codegen",
             "--smoke", str(path), "--symbol", symbol],
            capture_output=True, text=True, cwd=str(BASE_DIR),
            timeout=SMOKE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"smoke timed out (>{SMOKE_TIMEOUT_S}s) — likely infinite loop",
                "metrics": {}}
    out = proc.stdout.strip()
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return {"ok": False, "reason": f"no result (rc={proc.returncode}): {proc.stderr[:300]}",
                "metrics": {}}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return {"ok": False, "reason": f"bad smoke output: {e}", "metrics": {}}


# ── Main generate loop (CODEGEN stage handler core) ───────────────────────────

def generate_strategy(job: dict, spec: Optional[dict] = None,
                      max_retries: int = MAX_RETRIES) -> dict:
    """Generate + validate + smoke-test a strategy for `job`. On success sets
    job['strategy_id'] and job['artifacts']['code_file'] and returns
    {ok, path, strategy_id}. On exhaustion returns {ok: False, reason}.
    """
    from trading_agents.llm_fallback import chat_resilient

    if spec is None:
        spec_path = job.get("artifacts", {}).get("merged_spec")
        if not spec_path or not Path(spec_path).exists():
            return {"ok": False, "reason": "no merged_spec artifact"}
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))

    sid = job.get("strategy_id") or st.alloc_strategy_id()
    job["strategy_id"] = sid
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{sid.lower()}_{_slug(spec)}.py"
    client = _make_client()

    prev_code = prev_error = ""
    for attempt in range(1, max_retries + 1):
        job["retries"]["codegen"] = attempt
        try:
            raw = chat_resilient(
                client,
                system=_system_prompt(),
                user=_user_prompt(spec, sid, prev_code, prev_error),
                max_tokens=4000, model="claude-opus-4-8", thinking=True,
                nvidia_tier="ULTRA", label="factory_codegen",
            )
        except Exception as e:
            prev_error = f"LLM call failed: {e}"
            log.warning("[codegen] attempt %d LLM error: %s", attempt, e)
            continue

        code = _extract_code(raw)
        # Force the required STRATEGY_ID even if the model drifted.
        code = re.sub(r'STRATEGY_ID\s*=\s*["\']GS\d+["\']',
                      f'STRATEGY_ID = "{sid}"', code)
        path.write_text(code, encoding="utf-8")

        ok, errors = gl.validate_source(code)
        if not ok:
            prev_code, prev_error = code, "AST validation: " + "; ".join(errors[:6])
            log.warning("[codegen] attempt %d AST fail: %s", attempt, prev_error)
            continue

        smoke = run_smoke_subprocess(path, spec.get("symbols", ["XAUUSD"])[0]
                                     if spec.get("symbols") else "XAUUSD")
        if not smoke.get("ok"):
            prev_code, prev_error = code, "smoke: " + smoke.get("reason", "?")
            log.warning("[codegen] attempt %d smoke fail: %s", attempt, prev_error)
            continue

        job.setdefault("artifacts", {})["code_file"] = str(path)
        log.info("[codegen] %s generated OK on attempt %d -> %s", sid, attempt, path.name)
        return {"ok": True, "path": str(path), "strategy_id": sid,
                "attempts": attempt, "smoke": smoke}

    # All attempts exhausted — remove the broken candidate so it can't load.
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
    return {"ok": False, "reason": f"failed after {max_retries} attempts: {prev_error}"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", metavar="FILE", help="smoke-test a generated module")
    p.add_argument("--symbol", default="XAUUSD")
    args = p.parse_args()
    if args.smoke:
        result = smoke_test_file(Path(args.smoke), args.symbol)
        print(json.dumps(result))
        sys.exit(0 if result.get("ok") else 1)
    p.print_help()


if __name__ == "__main__":
    main()
