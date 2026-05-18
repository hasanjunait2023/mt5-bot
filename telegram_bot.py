"""
Telegram bot — gateway to Maic, the CEO Agent of Fx Vault MT5 Bot System.
Run: python telegram_bot.py
"""

import asyncio
import logging
import os
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

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Maic is online.\n\n"
        "I am the CEO Agent of the Fx Vault MT5 Bot System. "
        "Tell me what you need — I will think, delegate, and report back.\n\n"
        "Commands:\n"
        "/start — this message\n"
        "/reset — clear conversation history\n"
        "/status — system status"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    clear_history(chat_id)
    await update.message.reply_text("Conversation history cleared. Fresh session started.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "System Status:\n"
        "- Maic CEO Agent: Online\n"
        "- Telegram Bridge: Connected\n"
        "- Claude CLI: Active\n"
        "- MT5 Bridge: Available\n\n"
        "Send me any task or question."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id_int = update.effective_chat.id

    if ALLOWED_CHAT_ID and chat_id_int != ALLOWED_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return

    user_text = update.message.text
    chat_id = str(chat_id_int)
    logger.info(f"[Maic] Received from {update.effective_user.username}: {user_text[:80]}")

    await context.bot.send_chat_action(chat_id=chat_id_int, action=ChatAction.TYPING)

    response = maic_chat(chat_id, user_text)

    # Send in chunks if response is long (Telegram 4096 char limit)
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Maic CEO Agent bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
