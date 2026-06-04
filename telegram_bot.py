"""
Telegram bot — gateway to Maic (CEO Agent) and command center for the
Telegram HQ. Routes per forum topic: approvals in the EA Coach topic go
straight to EACoach; everything else talks to Maic.

Run: python telegram_bot.py
"""

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ChatAction

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

sys.path.insert(0, str(Path(__file__).parent))
from trading_agents.maic_ceo_agent import chat as maic_chat, clear_history
from trading_agents import telegram_hq

_NB_URL_RE = re.compile(r"https?://notebooklm\.google\.com/notebook/[A-Za-z0-9?=&_-]+")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

COACH_STATE = Path(__file__).parent / "logs" / "ea_agents" / "_coach_state.json"


# ───────────────────────── auth ─────────────────────────

def _group_chat_id() -> int:
    cfg = telegram_hq.load_config()
    gid = os.getenv("TELEGRAM_GROUP_CHAT_ID") or cfg.get("group_chat_id")
    try:
        return int(gid) if gid else 0
    except (TypeError, ValueError):
        return 0


def _authorized(chat_id: int) -> bool:
    return chat_id == ALLOWED_CHAT_ID or chat_id == _group_chat_id()


# ───────────────────────── commands ─────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Maic is online.\n\n"
        "I am the CEO Agent of the Fx Vault MT5 Bot System. "
        "Tell me what you need — I will think, delegate, and report back.\n\n"
        "Commands:\n"
        "/start — this message\n"
        "/reset — clear conversation history\n"
        "/status — system status\n"
        "/hq_setup — (run inside the HQ group) create all team topics\n"
        "/hq_status — show topic routing map"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    clear_history(chat_id)
    await update.message.reply_text("Conversation history cleared. Fresh session started.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "System Status:\n"
        "- Maic CEO Agent: Online\n"
        "- Telegram HQ: Connected\n"
        "- Claude CLI: Active\n"
        "- MT5 Bridge: Available\n\n"
        "Send me any task or question."
    )


async def hq_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "Run /hq_setup *inside the HQ supergroup*, not in a private chat.",
            parse_mode="Markdown")
        return
    if not getattr(chat, "is_forum", False):
        await update.message.reply_text(
            "This group does not have *Topics* enabled. Open the group → Edit → "
            "turn on *Topics*, make sure I'm an admin with *Manage Topics*, then "
            "run /hq_setup again.", parse_mode="Markdown")
        return

    await update.message.reply_text("Setting up Telegram HQ — creating team topics…")
    result = await asyncio.to_thread(telegram_hq.ensure_topics, chat.id)

    lines = ["*Telegram HQ setup*"]
    if result["created"]:
        lines.append("Created:\n" + "\n".join(f"• {t}" for t in result["created"]))
    if result["existing"]:
        lines.append("Already mapped:\n" + "\n".join(f"• {t}" for t in result["existing"]))
    if result["errors"]:
        lines.append("⚠️ Errors:\n" + "\n".join(f"• {e}" for e in result["errors"]))
    lines.append("✅ Setup complete." if result["setup_complete"]
                 else "Setup partial — fix the errors above and re-run /hq_setup.")
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def hq_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = telegram_hq.load_config()
    lines = [f"*Telegram HQ* — group `{cfg.get('group_chat_id') or 'not set'}`",
             f"Setup complete: {cfg.get('setup_complete')}", ""]
    for key, c in cfg.get("categories", {}).items():
        flag = "🟢" if c.get("enabled", True) else "⚪️"
        tid = c.get("thread_id") or "—"
        lines.append(f"{flag} {c.get('label', key)}  ·  thread `{tid}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ───────────────────────── approvals ─────────────────────────

def _pending_eas() -> dict:
    """EA name → pending question dict, for EAs awaiting a decision."""
    if not COACH_STATE.exists():
        return {}
    try:
        state = json.loads(COACH_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {ea: d["pending_question"]
            for ea, d in state.get("eas", {}).items()
            if d.get("pending_question")}


def _parse_answer(text: str) -> str | None:
    up = text.strip().upper()
    if "TEST" in up:
        return "TEST MORE"
    words = set(re.findall(r"[A-Z]+", up))
    if "YES" in words or up.startswith("Y"):
        return "YES"
    if "NO" in words or up == "N":
        return "NO"
    return None


async def _handle_approval(update: Update, text: str) -> bool:
    """Return True if this message was consumed as an EA approval reply."""
    pending = _pending_eas()
    if not pending:
        return False
    answer = _parse_answer(text)
    if not answer:
        return False

    # Which EA? explicit token in the message, else the only pending one.
    up = text.upper()
    named = [ea for ea in pending if ea.upper() in up]
    if named:
        ea_name = named[0]
    elif len(pending) == 1:
        ea_name = next(iter(pending))
    else:
        await update.message.reply_text(
            "Multiple EAs are awaiting a decision: "
            + ", ".join(pending)
            + f".\nReply with the EA name, e.g. `{next(iter(pending))} {answer}`.",
            parse_mode="Markdown")
        return True

    from trading_agents.ea_agents.ea_coach import record_user_answer
    result = await asyncio.to_thread(record_user_answer, ea_name, answer)
    await update.message.reply_text(result or f"Recorded {answer} for {ea_name}.")
    return True


# ───────────────────────── strategy factory ─────────────────────────

async def _handle_youtube(update: Update, text: str) -> bool:
    """If the message has a YouTube link, create a factory job. Returns True if
    consumed."""
    from trading_agents.factory import youtube as yt
    from trading_agents.factory import state as fst

    url = yt.extract_url(text)
    if not url:
        return False
    nb_match = _NB_URL_RE.search(text)
    notebook_url = nb_match.group(0) if nb_match else ""
    chat_ref = str(update.effective_chat.id)
    try:
        job = await asyncio.to_thread(fst.new_job, url, chat_id=chat_ref,
                                      notebook_url=notebook_url)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"Could not start factory job: {e}")
        return True

    msg = [f"🏭 Strategy Factory job *{job['job_id']}* started.",
           f"Video: {url}"]
    if notebook_url:
        msg.append("NotebookLM notebook linked ✅ — I'll run the A-to-Z research.")
    else:
        msg.append("⚠️ No NotebookLM notebook URL found. For deep research, create a "
                   "notebook, add this video as a source, and paste the notebook URL. "
                   "I'll still run transcript + chart-vision research without it.")
    msg.append("Track progress & approve gates in the dashboard → /factory.")
    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")
    return True


# ───────────────────────── message router ─────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id_int = update.effective_chat.id
    if not _authorized(chat_id_int):
        await update.message.reply_text("Unauthorized.")
        return

    user_text = update.message.text or ""
    thread_id = getattr(update.message, "message_thread_id", None)
    category = telegram_hq.category_for_thread(thread_id) if thread_id else None
    logger.info("[Maic] %s (topic=%s): %s",
                update.effective_user.username, category, user_text[:80])

    # YouTube link → kick off a Strategy Factory job (Option C: also grab the
    # NotebookLM notebook URL if the user pasted one alongside it).
    if await _handle_youtube(update, user_text):
        return

    # Approvals topic → try to consume as a YES/NO/TEST MORE decision first.
    if category == "ea_coach" and await _handle_approval(update, user_text):
        return

    await context.bot.send_chat_action(chat_id=chat_id_int, action=ChatAction.TYPING)

    # Per-topic conversation memory so each thread is its own dialogue with Maic.
    convo_key = f"{chat_id_int}_{thread_id}" if thread_id else str(chat_id_int)
    prompt = user_text
    if category and category not in ("ceo",):
        cfg = telegram_hq.load_config()
        label = cfg["categories"].get(category, {}).get("label", category)
        prompt = f"(message from the '{label}' HQ topic)\n{user_text}"

    response = maic_chat(convo_key, prompt)

    for i in range(0, len(response), 4096):
        await update.message.reply_text(response[i:i + 4096])
        if i + 4096 < len(response):
            await context.bot.send_chat_action(chat_id=chat_id_int, action=ChatAction.TYPING)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("hq_setup", hq_setup))
    app.add_handler(CommandHandler("hq_status", hq_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Maic CEO Agent bot is running...")
    # drop_pending_updates: on a (re)start, skip the backlog so Maic doesn't
    # re-answer old messages — matters while the dual-poller conflict causes
    # frequent restarts until the competing (VPS) instance is stopped.
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
