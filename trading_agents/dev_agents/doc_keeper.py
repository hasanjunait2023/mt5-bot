"""
DocKeeperAgent — Keeps docstrings and documentation up to date.

Finds recently changed Python files (last 7 days), generates docstrings for
functions that lack them, and regenerates docs/API.md.

Usage:
  python -m trading_agents.dev_agents.doc_keeper --scope mt5_bridge
  python -m trading_agents.dev_agents.doc_keeper --scope trading_agents
  python -m trading_agents.dev_agents.doc_keeper --all
"""

import ast
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("DocKeeperAgent")

BASE_DIR = Path(__file__).parent.parent.parent
DOCS_DIR = BASE_DIR / "docs"

SYSTEM_PROMPT = """You are DocKeeperAgent, a technical writer for a Python trading system.

Given a Python function or class and its context, write a concise docstring.
Rules:
- One-line summary first, then details if needed
- Document parameters and return values for public functions
- Note any side effects (file writes, API calls, MT5 operations)
- Keep it under 5 lines for simple functions
- Use imperative mood: "Connect to MT5" not "Connects to MT5"
- Return ONLY the docstring text (no quotes, no function definition)"""


def _get_recent_files(scope: str, days: int = 7) -> list[Path]:
    result = subprocess.run(
        ["git", "log", f"--since={days} days ago", "--name-only", "--pretty=format:", "--", f"{scope}/*.py"],
        capture_output=True, text=True, cwd=str(BASE_DIR),
    )
    paths = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith(".py"):
            p = BASE_DIR / line
            if p.exists():
                paths.append(p)
    return list(set(paths))


def _find_missing_docstrings(source: str) -> list[dict]:
    """Return list of {name, lineno, type} for functions/classes missing docstrings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not (node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)):
                missing.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                })
    return missing


def _add_docstrings(file_path: Path, client: anthropic.Anthropic) -> int:
    source = file_path.read_text(encoding="utf-8")
    missing = _find_missing_docstrings(source)
    if not missing:
        return 0

    count = 0
    lines = source.splitlines(keepends=True)

    # process in reverse order so line numbers stay valid
    for item in reversed(missing):
        lineno = item["lineno"] - 1  # 0-indexed
        name = item["name"]
        # get 20 lines of context around the definition
        context = "".join(lines[max(0, lineno):min(len(lines), lineno + 20)])

        import sys as _sys, pathlib as _pl
        _ta = str(_pl.Path(__file__).resolve().parents[1])
        if _ta not in _sys.path: _sys.path.insert(0, _ta)
        from llm_fallback import chat_resilient
        # Haiku (unchanged, no thinking) + NVIDIA fallback if Claude is down
        docstring = chat_resilient(
            client, system=SYSTEM_PROMPT,
            user=f"Write a docstring for this {item['type']}:\n\n{context}",
            max_tokens=256, model="claude-haiku-4-5-20251001", thinking=False,
            nvidia_tier="LIGHT", label="doc_keeper").strip('"').strip("'")

        # find the line after the def/class line to insert docstring
        insert_line = lineno + 1
        # find the colon that ends the signature (may span multiple lines)
        i = lineno
        while i < len(lines) and ":" not in lines[i].split("#")[0]:
            i += 1
        insert_line = i + 1

        indent = "    " if item["type"] == "function" else "    "
        # detect existing indentation
        if insert_line < len(lines):
            existing_indent = len(lines[insert_line]) - len(lines[insert_line].lstrip())
            indent = " " * existing_indent

        docstring_line = f'{indent}"""{docstring}"""\n'
        lines.insert(insert_line, docstring_line)
        count += 1

    file_path.write_text("".join(lines), encoding="utf-8")
    return count


def process_scope(scope: str, client: anthropic.Anthropic) -> int:
    files = _get_recent_files(scope)
    if not files:
        log.info("No recently changed files in %s", scope)
        return 0
    total = 0
    updated = []
    for f in files:
        added = _add_docstrings(f, client)
        if added:
            total += added
            updated.append(f.name)
            log.info("Added %d docstrings to %s", added, f.name)
    if updated:
        notify(f"*DocKeeper*: Added {total} docstrings across {len(updated)} files: {', '.join(updated)}")
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if "--all" in sys.argv:
        scopes = ["mt5_bridge", "trading_agents", "dashboard/backend"]
    elif "--scope" in sys.argv:
        scopes = [sys.argv[sys.argv.index("--scope") + 1]]
    else:
        print("Usage: python -m trading_agents.dev_agents.doc_keeper --scope mt5_bridge | --all")
        sys.exit(1)

    total = 0
    for scope in scopes:
        total += process_scope(scope, client)
    print(f"Total docstrings added: {total}")
