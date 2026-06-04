"""Maic Telegram Bot — inbound listener using python-telegram-bot.

Routes messages to maic_ceo_agent.chat(). Responds in the CEO topic
(thread 11) for group messages, private chat for DMs.

Commands:
  /clear  — wipe Maic's conversation history for this chat
  /status — list running Python processes
  /help   — command list

Usage:
  python -m trading_agents.maic_telegram_bot
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)
log = logging.getLogger("MaicBot")

CEO_THREAD_ID  = 11       # "🧭 CEO · Maic" forum topic
GROUP_CHAT_ID  = -1003809133423
MAX_MSG_LEN    = 4000


_REDACT_RE = __import__("re").compile(
    r"(?i)(api.?key|token|password|secret|bearer|auth)[=:\s]\S+", flags=0
)

def _running_procs() -> str:
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "CommandLine"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [
            l.strip() for l in result.stdout.splitlines()
            if l.strip() and "wmic" not in l.lower() and "CommandLine" not in l
        ]
        redacted = [_REDACT_RE.sub(r"\1=***", l) for l in lines]
        return "\n".join(f"• `{l[:90]}`" for l in redacted) or "No Python processes found."
    except Exception as e:
        return f"Could not query processes: {e}"


def _allowed_ids() -> set[int]:
    raw = os.getenv("MAIC_ALLOWED_USER_IDS", "")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _maic_chat(history_key: str, text: str) -> str:
    sys.path.insert(0, str(BASE_DIR))
    from trading_agents.maic_ceo_agent import chat as _chat
    return _chat(history_key, text)


def _maic_clear(history_key: str) -> None:
    sys.path.insert(0, str(BASE_DIR))
    from trading_agents.maic_ceo_agent import clear_history
    clear_history(history_key)


async def _send_long(update, context, text: str) -> None:
    """Send text, splitting into chunks if over Telegram's 4096-char limit."""
    chunks = [text[i:i + MAX_MSG_LEN] for i in range(0, max(len(text), 1), MAX_MSG_LEN)]
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)


async def handle_message(update, context) -> None:
    from telegram import Update

    msg       = update.message
    if not msg or not msg.text:
        return

    chat_type = msg.chat.type
    text      = msg.text.strip()
    thread_id = msg.message_thread_id
    from_id   = msg.from_user.id if msg.from_user else 0

    # Group: only respond in CEO topic (thread 11)
    if chat_type in ("group", "supergroup"):
        if thread_id != CEO_THREAD_ID:
            return
        history_key = f"group_{msg.chat.id}"
    else:
        history_key = str(from_id)

    log.info("Message from %s (thread=%s): %s", from_id, thread_id, text[:100])

    # Auth gate — reject anyone not in MAIC_ALLOWED_USER_IDS
    allowed = _allowed_ids()
    if allowed and from_id not in allowed:
        log.warning("Rejected unauthorised user %s", from_id)
        return

    if text.startswith("/clear"):
        try:
            _maic_clear(history_key)
            await update.message.reply_text("✅ Maic history cleared.")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Could not clear: {e}")
        return

    if text.startswith("/status"):
        procs = _running_procs()
        await _send_long(update, context, f"*Running Python Processes:*\n{procs}")
        return

    if text.startswith("/help"):
        help_text = (
            "*Maic — CEO Agent Commands:*\n"
            "/status — list running bot processes\n"
            "/clear  — reset conversation history\n"
            "/help   — this message\n\n"
            "Send any message to talk to Maic."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=msg.chat.id,
        action="typing",
        **({"message_thread_id": thread_id} if thread_id else {}),
    )

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _maic_chat, history_key, text)
        await _send_long(update, context, response)
    except Exception as e:
        log.error("Maic chat error: %s", e)
        await update.message.reply_text(f"⚠️ Maic error: {e}")


def main() -> None:
    from telegram.ext import Application, MessageHandler, filters

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, handle_message))

    log.info("Maic Telegram Bot starting (group=%d CEO_thread=%d)", GROUP_CHAT_ID, CEO_THREAD_ID)
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    main()
