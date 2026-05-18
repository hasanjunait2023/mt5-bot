Organize the MT5 bot project root directory by moving loose files into their correct folders.

## Rules

**Keep at root (do not move):**
- `.env`, `.env.example`, `.gitignore`, `requirements.txt`, `package.json`, `package-lock.json`
- All `.bat` and `.ps1` startup/management scripts (start_bot, start_dashboard, START_LIVE_TRADER, STOP_LIVE_TRADER, MANAGE_STARTUP, install)
- `README.md` if present

**Move to `results/`:**
- Any `backtest_*.txt` files
- Any `*_report.txt` or `*_table.txt` files

**Move to `docs/`:**
- Any `*.md` files (except README.md at root)
- Any `*_SETUP*`, `*_INSTRUCTIONS*`, `*_ANNOUNCEMENT*` files

**Move to `scripts/`:**
- Any `.py` files that are utility/helper scripts (not part of a module)
- Examples: debug_*.py, load_*.py, run_*.py, trigger_*.py, click_*.py

**Move to `logs/`** (create if missing):
- Any `*_log.txt`, `*_install.txt`, `compile_*.txt` files

**Delete (after confirming with user):**
- Obvious temp/junk files: `final_answer.txt`, `alignment_verification.txt`, `bridge_test.txt`, `py_search.txt`, or any file that looks like a one-off debug artifact

## Steps

1. Run `Get-ChildItem "c:\Users\Junait\mt5 bot" -File` to see current root files
2. Categorize each loose file using the rules above
3. Show the user a plan (what moves where, what gets deleted)
4. Ask for confirmation on any deletes
5. Execute: create missing folders, move files, delete confirmed junk
6. Show final clean root structure
