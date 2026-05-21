"""
TestWriterAgent — Generates pytest test suites for any Python module.

Usage:
  python -m trading_agents.dev_agents.test_writer --file mt5_bridge/backtest.py
  python -m trading_agents.dev_agents.test_writer --file trading_agents/execution_manager.py
"""

import ast
import logging
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("TestWriterAgent")

BASE_DIR = Path(__file__).parent.parent.parent
TESTS_DIR = BASE_DIR / "tests"

SYSTEM_PROMPT = """You are TestWriterAgent, an expert Python test engineer.

Given a Python source file, generate a complete pytest test suite.

Rules:
- Use pytest fixtures and parametrize where appropriate
- Mock all external dependencies: MetaTrader5 (mt5), anthropic.Anthropic, requests, file I/O
- Mock MT5 calls with: @patch('MetaTrader5.initialize', return_value=True)
- Mock Anthropic with: @patch('anthropic.Anthropic')
- Cover happy paths, edge cases, and error handling
- Use descriptive test names: test_<function>_<scenario>
- Include at least one parametrized test where it makes sense
- Keep tests focused and independent (no shared mutable state)
- Do NOT import the module with live connections — always patch at module level

Output ONLY the Python test file content, starting with imports. No markdown, no explanation."""


def _extract_symbols(source: str) -> list[str]:
    """Extract function and class names via AST."""
    try:
        tree = ast.parse(source)
        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    symbols.append(node.name)
        return symbols
    except SyntaxError:
        return []


def write_tests(target: Path, client: anthropic.Anthropic) -> Path:
    """Generate tests for target file and write to tests/ directory."""
    source = target.read_text(encoding="utf-8", errors="replace")
    symbols = _extract_symbols(source)
    symbol_list = ", ".join(symbols[:20]) if symbols else "unknown"

    user_msg = (
        f"File: {target.relative_to(BASE_DIR)}\n"
        f"Public symbols to test: {symbol_list}\n\n"
        f"Source code:\n```python\n{source[:8000]}\n```"
    )

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    test_code = chat_resilient(
        client, system=SYSTEM_PROMPT, user=user_msg, max_tokens=4096,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="HEAVY",
        label="test_writer")
    # strip markdown code fences if present
    if test_code.startswith("```"):
        test_code = "\n".join(test_code.split("\n")[1:])
    if test_code.endswith("```"):
        test_code = "\n".join(test_code.split("\n")[:-1])

    TESTS_DIR.mkdir(exist_ok=True)
    out_path = TESTS_DIR / f"test_{target.stem}.py"
    out_path.write_text(test_code, encoding="utf-8")
    log.info("Tests written to %s", out_path)

    test_count = test_code.count("\ndef test_")
    notify(f"*TestWriter*: Wrote ~{test_count} tests for `{target.name}` → `tests/test_{target.stem}.py`\nRun: `pytest tests/test_{target.stem}.py`")
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--file" not in sys.argv:
        print("Usage: python -m trading_agents.dev_agents.test_writer --file <path>")
        sys.exit(1)
    idx = sys.argv.index("--file")
    target = BASE_DIR / sys.argv[idx + 1]
    if not target.exists():
        print(f"File not found: {target}")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    out = write_tests(target, client)
    print(f"Tests written to: {out}")
