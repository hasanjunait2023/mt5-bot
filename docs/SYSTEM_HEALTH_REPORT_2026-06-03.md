# MT5 Bot — System Health Report

**Date:** 2026-06-03 · **Branch:** master · **Scope:** full repo (260 of our Python files, dashboard, CI, security, infra)

---

## TL;DR (এক নজরে)

System-er foundation **strong** — code clean, secrets safe, structure ekhon organized. Kintu ekta **live-money trading system** hisebe duita boro gap ache:

1. **Almost no automated tests** (260 file, ~2 test). Live money, kono safety net nai.
2. **CI te kono test/lint gate nai** — broken code soja live VPS-e deploy hoye jete pare.

Eta duita na thakle, ekta bug → silent missed trade ba wrong lot size → real capital loss, ar keu janbe na agei. Baki sob mostly fine.

**If you do only one thing:** money-path test + CI gate (niche #1 + #2).

---

## What's healthy ✅

| Area | Finding |
|---|---|
| Code parses | 223/223 core files compile clean, 0 broken modules |
| Secrets | `.env` gitignored, **0 hardcoded credentials** in code |
| Tech debt | Only 2 TODO/FIXME in whole codebase |
| Auth infra | Login + token auth + CORS allowlist **now coded** (`core/auth.py`) |
| Structure | Root organized (backtest cluster + docs foldered), imports verified |

Foundation ভালো। Niche-r jinis gulo "missing safety", "broken" na.

---

## What needs attention ⚠️ (risk order)

### 🔴 1. No automated tests — CRITICAL
- **Fact:** 260 Python files, ~2 real tests.
- **Why it matters:** Eta real taka trade kore. Kono test nai mane — risk sizing, order fill, daily-DD halt, go-live gate — egulor kono ekta chup chap bhul korle dhora porbe na, until taka chole jay.
- **Real failure example:** `_fill_order` auto-detect bug (memory te ache) ekta live blocker chilo — ekta test thakle agei dhora porto.
- **Fix:** pytest setup + ~20 targeted test on money-path (coverage % chasing na, just scary path gulo).
- **Effort:** CC ~30-45 min. Manually: 1-2 days.

### 🔴 2. CI has no test/lint gate — HIGH
- **Fact:** `.github/workflows/` te `deploy-vps.yml`, `deploy-local`, `migrations` — kintu deploy-er age kono check nai.
- **Why it matters:** Broken commit → soja live trader-e deploy. Tomar safety hocche "ami bhul korbo na" — eta enough na production-e.
- **Fix:** `ci.yml` → `compileall` + `ruff` + `pytest`, deploy-er age fail korle deploy block.
- **Effort:** CC ~15 min. (Needs #1 to be useful.)

### 🟠 3. Dashboard auth is FAIL-OPEN — verify on VPS
- **Fact:** Auth code ache, kintu **default OFF** — `DASHBOARD_PASSWORD` set na thakle kono auth nai; `DASHBOARD_ALLOWED_ORIGINS` set na thakle CORS = `*`.
- **Local `.env`:** password set ✅, origins commented out.
- **Why it matters:** Public VPS. VPS-er `.env` te jodi `DASHBOARD_PASSWORD` na thake → dashboard puro **open to internet**, jekeu trade control korte parbe.
- **Fix:** VPS `.env` te duita key confirm/set. (Token auth thakle CORS `*` tolerable, tobu tighten koro.)
- **Effort:** CC ~5 min (SSH verify).

### 🟠 4. 289 broad/bare `except` — silent-failure risk
- **Fact:** Core code-e 289 ta `except Exception:` / `except:`.
- **Why it matters:** Telemetry code-e fine. Kintu **order placement / risk path**-e ekta swallowed exception mane — failed live order ba DD-breach chup chap pass hoye gelo, kono alert na.
- **Fix:** Sudhu execution + risk modules audit — proti except log + Telegram alert kore, `pass` na.
- **Effort:** CC ~20 min audit.

### 🟡 5. No lint tooling / dep pinning — LOW
- **Fact:** `ruff`/`pytest` installed na, requirements loose.
- **Fix:** ruff config + critical dep pin. Cheap, #1/#2 ke clean kore.
- **Effort:** CC ~10 min.

---

## Decision helper

| # | Item | Risk | CC effort | Do it? |
|---|---|---|---|---|
| 1 | Money-path tests | 🔴 Critical | ~40 min | **Recommended now** |
| 2 | CI test gate | 🔴 High | ~15 min | **Recommended now** (with #1) |
| 3 | VPS auth verify | 🟠 High | ~5 min | Quick win — do anytime |
| 4 | Silent-failure audit | 🟠 Med | ~20 min | After #1 |
| 5 | Lint + dep pin | 🟡 Low | ~10 min | Bundle with #2 |

**Suggested path:** #3 first (5 min, closes security), then #1+#2 together (the real safety net).

---

## Completion status (updated 2026-06-03)

| # | Item | Status |
|---|---|---|
| 1 | Money-path tests | ✅ **Done** — 26 tests (risk sizing, 6% DD halt, trade caps, spread, fail-closed go-live gate). Commit `32e37ae`. |
| 2 | CI test gate | ✅ **Done** — `ci.yml` (ruff+compileall+pytest); `deploy-vps.yml` now `needs: test`. Caught + fixed 5 latent undefined-name bugs. |
| 3 | VPS auth verify | ⏳ **Pending** — needs prod VPS shell (security-gated). User to run the one-liner or grant access. |
| 4 | Silent-failure audit | ✅ **Done** — 1 fail-open bug fixed (corrupt kill-switch silently resumed trading → now fails safe + tested). Rest benign by design. |
| 5 | Lint + dep pinning | ✅ **Done** — `ruff.toml` (bug-subset) + `requirements-dev.txt`. requirements.txt already `>=`-constrained; no hard-pin (would add risk, not value). |

## Notes
- Original analysis was read-only; safety-net work above is committed (`32e37ae`).
- Memory updated: dashboard security posture (auth implemented, fail-open default).
