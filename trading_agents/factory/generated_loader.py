"""Safe loader + AST allow-list for factory-generated strategies.

Generated strategies are LLM-written Python that gets exec'd and trusted to make
trading signals. Defense in depth:
  1. Static AST allow-list BEFORE any import (this module).
  2. Process isolation for smoke-test (factory/codegen.py --smoke).
  3. Loader re-validates on every load and isolates each module in try/except, so
     a bad generated file can never break the hand-written core strategies.

Each generated module (trading_agents/scalp/generated/gsNN_slug.py) must expose:
  STRATEGY_ID   : str   e.g. "GS50"
  TIMEFRAME     : str   "M1" | "M3" | "M5" | "M15"
  SYMBOLS       : list[str]
  STRATEGY_FN   : callable(bars, t_i, spread, symbol="...") -> dict|None
"""
from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("factory.loader")

BASE_DIR = Path(__file__).resolve().parents[2]
GENERATED_DIR = BASE_DIR / "trading_agents" / "scalp" / "generated"

# The ONLY indicator names a generated strategy may import. Mirrors the public
# surface of trading_agents/scalp/indicators.py.
INDICATOR_CATALOG = {
    "ema", "_ema_arr", "atr", "rsi", "stoch", "bollinger", "keltner",
    "vwap_session", "ema_cross", "ema_above", "swing_high", "swing_low",
    "has_bullish_fvg", "has_bearish_fvg", "find_fvg_zones", "find_inverse_fvg",
    "detect_liquidity_sweep", "detect_trendline_break", "session_info",
}

# Modules a generated file may import from (besides indicators).
ALLOWED_IMPORT_MODULES = {"math"}
ALLOWED_IMPORT_FROM = {"__future__", "math", "trading_agents.scalp.indicators"}

# Builtins / names that must never appear.
BLOCKED_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "input", "exit", "quit",
    "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "os", "sys", "subprocess", "socket", "shutil", "requests", "importlib",
    "builtins", "pathlib", "Path", "pickle", "marshal", "ctypes", "threading",
    "multiprocessing", "urllib", "http", "json", "io", "tempfile",
}

VALID_TF = {"M1", "M3", "M5", "M15", "M30", "H1"}


class _Validator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def _err(self, node: ast.AST, msg: str) -> None:
        self.errors.append(f"line {getattr(node, 'lineno', '?')}: {msg}")

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.name not in ALLOWED_IMPORT_MODULES:
                self._err(node, f"disallowed import '{a.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if mod not in ALLOWED_IMPORT_FROM:
            self._err(node, f"disallowed import-from '{mod}'")
        elif mod == "trading_agents.scalp.indicators":
            for a in node.names:
                if a.name not in INDICATOR_CATALOG:
                    self._err(node, f"unknown indicator '{a.name}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.attr, str) and node.attr.startswith("__"):
            self._err(node, f"dunder attribute access '{node.attr}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BLOCKED_NAMES:
            self._err(node, f"blocked name '{node.id}'")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._err(node, "class definitions not allowed")

    def visit_AsyncFunctionDef(self, node) -> None:  # type: ignore[override]
        self._err(node, "async functions not allowed")

    def visit_Await(self, node) -> None:  # type: ignore[override]
        self._err(node, "await not allowed")

    def visit_With(self, node) -> None:  # type: ignore[override]
        self._err(node, "with-statements not allowed")


def validate_source(source: str) -> tuple[bool, list[str]]:
    """Static allow-list check. Returns (ok, errors)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]
    v = _Validator()
    v.visit(tree)
    return (not v.errors), v.errors


def validate_file(path: Path) -> tuple[bool, list[str]]:
    return validate_source(Path(path).read_text(encoding="utf-8"))


def load_module(path: Path):
    """Validate then import a generated module from file. Raises on validation
    failure or import error. Returns the loaded module object.
    """
    path = Path(path)
    ok, errors = validate_file(path)
    if not ok:
        raise ValueError(f"AST validation failed: {errors}")
    mod_name = f"factory_generated_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create import spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # noqa: S102 — gated by validate_file above
    return mod


def _extract(mod) -> tuple[str, str, list[str], Callable]:
    sid = getattr(mod, "STRATEGY_ID", None)
    tf = getattr(mod, "TIMEFRAME", None)
    syms = getattr(mod, "SYMBOLS", None)
    fn = getattr(mod, "STRATEGY_FN", None)
    if not (isinstance(sid, str) and sid.startswith("GS")):
        raise ValueError("missing/invalid STRATEGY_ID")
    if tf not in VALID_TF:
        raise ValueError(f"invalid TIMEFRAME {tf!r}")
    if not (isinstance(syms, list) and syms):
        raise ValueError("missing/empty SYMBOLS")
    if not callable(fn):
        raise ValueError("missing STRATEGY_FN callable")
    return sid, tf, list(syms), fn


def register_into(strategies: dict, strategy_symbols: dict) -> list[str]:
    """Load every generated module and register it into the given dicts.

    Never overwrites an existing (hand-written) id. Each module is isolated:
    a bad file is logged and skipped, never fatal. Returns ids registered.
    """
    registered: list[str] = []
    if not GENERATED_DIR.exists():
        return registered
    for path in sorted(GENERATED_DIR.glob("gs*_*.py")):
        try:
            mod = load_module(path)
            sid, tf, syms, fn = _extract(mod)
            if sid in strategies:
                log.warning("[loader] %s already registered — skipping %s", sid, path.name)
                continue
            strategies[sid] = (tf, fn)
            strategy_symbols[sid] = syms
            registered.append(sid)
            log.info("[loader] registered %s (%s, %s) from %s", sid, tf, syms, path.name)
        except Exception as e:  # noqa: BLE001 — isolation is the point
            log.error("[loader] skip %s: %s", path.name, e)
    return registered
