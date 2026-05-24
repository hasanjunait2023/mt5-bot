"""
NVIDIA NIM Model Router for MT5 Trading Bot
============================================
Routes tasks to the right model tier so lightweight tasks (heartbeat,
quick checks) use fast/cheap models and complex tasks (strategy research,
optimization) use the most powerful models.

Tier map:
  NANO   (~1-4B)  : heartbeat, ping, boolean checks
  LIGHT  (~4-12B) : market status, quick signal filter
  MEDIUM (~49-70B): signal analysis, trade validation, news
  HEAVY  (~253B+) : strategy research, deep analysis, optimization
"""

import os
import re
import time
import logging
from typing import Any, Dict, Optional
from datetime import datetime

log = logging.getLogger("NvidiaRouter")

# ── API config ────────────────────────────────────────────────────────────────
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "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")

# ── Model tiers ───────────────────────────────────────────────────────────────
# Each tier lists primary + fallback models
MODELS = {
    # Fastest — 1B; heartbeat / boolean yes-no (confirmed ✅)
    "NANO": {
        "primary":   "meta/llama-3.2-1b-instruct",
        "fallback":  "meta/llama-3.1-8b-instruct",
        "max_tokens": 64,
        "timeout":   30,
        "description": "Heartbeat, ping, boolean status checks",
    },

    # Quick — 8B Nemotron Nano; quick filter (confirmed ✅ ~4s)
    "LIGHT": {
        "primary":   "nvidia/llama-3.1-nemotron-nano-8b-v1",
        "fallback":  "meta/llama-3.1-8b-instruct",
        "max_tokens": 256,
        "timeout":   30,
        "description": "Market status, quick signal filter, log summary",
    },

    # Workhorse — 70B Llama; signal analysis, trade decisions (confirmed ✅ ~4s)
    "MEDIUM": {
        "primary":   "meta/llama-3.3-70b-instruct",
        "fallback":  "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "max_tokens": 1024,
        "timeout":   60,
        "description": "Signal analysis, trade validation, news sentiment",
    },

    # Deep — Nemotron Super 49B v1.5 (fastest heavy, ✅ 1.5s); v1 as fallback (✅ 6.7s)
    "HEAVY": {
        "primary":   "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "fallback":  "nvidia/llama-3.3-nemotron-super-49b-v1",
        "max_tokens": 2048,
        "timeout":   120,
        "description": "Strategy research, deep analysis, optimization",
    },

    # Ultra — mistral-large-3 675B (confirmed ✅ 6.4s); for future deepest analysis
    "ULTRA": {
        "primary":   "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "fallback":  "nvidia/llama-3.3-nemotron-super-49b-v1",
        "max_tokens": 4096,
        "timeout":   180,
        "description": "Deepest multi-symbol analysis, rare complex decisions",
    },
}

# Task → tier routing table
TASK_TIER = {
    # NANO
    "heartbeat":        "NANO",
    "ping":             "NANO",
    "alive_check":      "NANO",
    # LIGHT
    "market_status":    "LIGHT",
    "quick_filter":     "LIGHT",
    "log_summary":      "LIGHT",
    "session_check":    "LIGHT",
    # MEDIUM
    "signal_analysis":  "MEDIUM",
    "trade_decision":   "MEDIUM",
    "news_sentiment":   "MEDIUM",
    "risk_check":       "MEDIUM",
    # HEAVY
    "strategy_research":"HEAVY",
    "optimization":     "HEAVY",
    "deep_analysis":    "HEAVY",
    # ULTRA
    "multi_symbol":     "ULTRA",
    "full_report":      "ULTRA",
}


# ── Client ────────────────────────────────────────────────────────────────────

def _get_client():
    """Return an OpenAI client pointed at NVIDIA NIM."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed — run: pip install openai")
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)


def _chat(model: str, system: str, user: str, max_tokens: int,
          temperature: float = 0.2, timeout: int = 60) -> str:
    """Single chat completion call; returns the assistant text."""
    client = _get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    msg = resp.choices[0].message
    # Strip any <think>...</think> reasoning the model inlines into content.
    content = re.sub(r"<think>.*?</think>", "",
                     getattr(msg, "content", None) or "", flags=re.S).strip()
    # Nemotron-style reasoning models leave content empty and put the answer in
    # reasoning_content. Recover it so the NVIDIA fallback never silently fails.
    if not content:
        rc = re.sub(r"^<think>.*?</think>\s*", "",
                    getattr(msg, "reasoning_content", None) or "", flags=re.S).strip()
        content = rc or (getattr(msg, "reasoning_content", None) or "").strip()
    if not content:
        raise ValueError(f"Model {model} returned empty content")
    return content.strip()


# ── Public API ────────────────────────────────────────────────────────────────

def ask(task: str, prompt: str, context: str = "", temperature: float = 0.2) -> Dict[str, Any]:
    """
    Route a task to the correct model tier and return the response.

    Args:
        task       : one of the keys in TASK_TIER
        prompt     : the user message / question
        context    : optional system-level context to prepend
        temperature: 0.0 = deterministic, 1.0 = creative

    Returns dict with keys: task, tier, model, response, latency_ms
    """
    tier_name = TASK_TIER.get(task, "MEDIUM")
    tier      = MODELS[tier_name]
    model     = tier["primary"]
    system    = context or f"You are a trading assistant. Task: {tier['description']}. Be concise."

    timeout = tier.get("timeout", 60)
    t0 = time.perf_counter()
    try:
        response = _chat(model, system, prompt, tier["max_tokens"], temperature, timeout)
        latency  = int((time.perf_counter() - t0) * 1000)
        log.debug(f"[{tier_name}] {model} → {latency}ms")
        return {
            "task": task, "tier": tier_name, "model": model,
            "response": response, "latency_ms": latency, "ok": True,
        }
    except Exception as e:
        # Try fallback model
        fallback = tier.get("fallback")
        if fallback and fallback != model:
            log.warning(f"Primary {model} failed ({e}), trying fallback {fallback}")
            try:
                response = _chat(fallback, system, prompt, tier["max_tokens"], temperature, timeout)
                latency  = int((time.perf_counter() - t0) * 1000)
                return {
                    "task": task, "tier": tier_name, "model": fallback,
                    "response": response, "latency_ms": latency, "ok": True,
                    "used_fallback": True,
                }
            except Exception as e2:
                log.error(f"Fallback also failed: {e2}")
        return {
            "task": task, "tier": tier_name, "model": model,
            "response": None, "latency_ms": 0, "ok": False, "error": str(e),
        }


# ── Pre-built task helpers ────────────────────────────────────────────────────

def heartbeat() -> bool:
    """Minimal alive-check. Returns True if API is reachable."""
    result = ask(
        task="heartbeat",
        prompt='Reply with exactly one word: "alive"',
    )
    return result["ok"] and "alive" in (result["response"] or "").lower()


def market_status_check(symbol: str, current_spread: float, session: str) -> str:
    """Quick check: should we consider trading this symbol right now?"""
    result = ask(
        task="market_status",
        prompt=(
            f"Symbol: {symbol}, Spread: {current_spread:.1f} pips, Session: {session}.\n"
            "Is this spread acceptable for scalping? Reply YES or NO with one short reason."
        ),
    )
    return result.get("response", "UNKNOWN")


def quick_signal_filter(symbol: str, signal: str, rsi: float, trend: str) -> str:
    """Lightweight pass/skip decision before deeper analysis."""
    result = ask(
        task="quick_filter",
        prompt=(
            f"Symbol: {symbol} | Signal: {signal} | RSI: {rsi:.1f} | Trend: {trend}\n"
            "Should this signal be passed for full analysis? Reply PASS or SKIP."
        ),
    )
    return result.get("response", "SKIP")


def analyze_signal(symbol: str, timeframe: str, indicators: Dict) -> str:
    """Medium-depth signal analysis using a 70B model."""
    ind_str = "\n".join(f"  {k}: {v}" for k, v in indicators.items())
    result = ask(
        task="signal_analysis",
        prompt=(
            f"Analyze this trading signal:\nSymbol: {symbol} | TF: {timeframe}\n"
            f"Indicators:\n{ind_str}\n\n"
            "Provide: LONG/SHORT/NEUTRAL, confidence (0-100%), key risk factors."
        ),
    )
    return result.get("response", "")


def research_strategy(symbol: str, market_context: str, recent_performance: str) -> str:
    """Deep strategy research using the 253B Nemotron Ultra model."""
    result = ask(
        task="strategy_research",
        prompt=(
            f"Develop a new trading strategy for {symbol}.\n"
            f"Market context: {market_context}\n"
            f"Recent performance summary: {recent_performance}\n\n"
            "Suggest: entry rules, SL/TP logic, session filter, and risk management."
        ),
        temperature=0.4,
    )
    return result.get("response", "")


def analyze_news_sentiment(headline: str, symbol: str) -> str:
    """Assess news impact on a symbol."""
    result = ask(
        task="news_sentiment",
        prompt=(
            f"News: {headline}\nSymbol affected: {symbol}\n"
            "Rate sentiment: BULLISH / BEARISH / NEUTRAL. Give a confidence % and brief reason."
        ),
    )
    return result.get("response", "")


def optimize_parameters(symbol: str, current_params: Dict, backtest_summary: str) -> str:
    """Use the heavy model to suggest parameter improvements."""
    params_str = "\n".join(f"  {k}: {v}" for k, v in current_params.items())
    result = ask(
        task="optimization",
        prompt=(
            f"Optimize trading parameters for {symbol}.\n"
            f"Current parameters:\n{params_str}\n"
            f"Backtest summary: {backtest_summary}\n\n"
            "Suggest specific parameter changes to improve Sharpe ratio and reduce drawdown."
        ),
        temperature=0.3,
    )
    return result.get("response", "")


# ── Verification / self-test ──────────────────────────────────────────────────

def verify_all_tiers(verbose: bool = True) -> Dict[str, bool]:
    """
    Test all four model tiers. Prints a summary table.
    Returns {tier_name: passed}.
    """
    print("\n" + "=" * 60)
    print("  NVIDIA NIM Model Router — Tier Verification")
    print("=" * 60)

    tests = {
        "NANO":   ("heartbeat",      'Reply with exactly one word: "alive"'),
        "LIGHT":  ("market_status",  "Is EURUSD a major forex pair? Reply YES or NO."),
        "MEDIUM": ("signal_analysis","What does RSI above 70 typically indicate? One sentence."),
        "HEAVY":  ("strategy_research", "Name one advantage of multi-timeframe analysis. One sentence."),
    }

    results = {}
    for tier_name, (task, prompt) in tests.items():
        model = MODELS[tier_name]["primary"]
        print(f"\n  [{tier_name}] {model}")
        print(f"  Task   : {task}")
        t0 = time.perf_counter()
        res = ask(task=task, prompt=prompt)
        ms  = int((time.perf_counter() - t0) * 1000)
        ok  = res["ok"]
        results[tier_name] = ok
        if ok:
            preview = (res["response"] or "")[:80].replace("\n", " ")
            fallback_note = " (fallback)" if res.get("used_fallback") else ""
            print(f"  Status : PASS{fallback_note} | {ms}ms")
            print(f"  Reply  : {preview}...")
        else:
            print(f"  Status : FAIL — {res.get('error', 'unknown error')}")

    print("\n" + "=" * 60)
    passed = sum(results.values())
    total  = len(results)
    print(f"  Result : {passed}/{total} tiers operational")
    print("=" * 60 + "\n")
    return results


# ── CLI entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    if "--verify" in sys.argv or len(sys.argv) == 1:
        results = verify_all_tiers()
        sys.exit(0 if all(results.values()) else 1)

    # Quick demo
    print("Heartbeat:", heartbeat())
    print("\nMarket status check:")
    print(market_status_check("XAUUSD", 2.5, "London"))
    print("\nSignal filter:")
    print(quick_signal_filter("EURUSD", "LONG", 58.3, "UPTREND"))
