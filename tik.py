#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import asyncio
from pathlib import Path
from functools import wraps
from threading import Thread

from flask import Flask
from telegram import Update, ChatMember, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
import yt_dlp
import diskcache
from dotenv import load_dotenv

# —————————————————————————————————————————
# تحميل إعدادات البيئة من .env
# —————————————————————————————————————————
load_dotenv()
TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@yourchannel")
DOWNLOAD_DIR     = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
CACHE_DIR        = Path(os.getenv("CACHE_DIR", "cache"))
MAX_CACHE_SIZE   = int(os.getenv("MAX_CACHE_SIZE", "1000000000"))

# تأكد من وجود مجلّدات التحميل والكاش
DOWNLOAD_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# —————————————————————————————————————————
# Flask Keep-Alive Web Server
# —————————————————————————————————————————
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# —————————————————————————————————————————
# Logging
# —————————————————————————————————————————
logging.basicConfig(
    format="%(asctime)s %(levelname)s ▶ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# —————————————————————————————————————————
# Cache to avoid re-downloading same URL
# —————————————————————————————————————————
cache = diskcache.Cache(str(CACHE_DIR), size_limit=MAX_CACHE_SIZE)

# —————————————————————————————————————————
# In-memory user sessions
# —————————————————————————————————————————
user_sessions = {}  # { user_id: platform_choice }

# —————————————————————————————————————————
# Decorator to enforce channel membership
# —————————————————————————————————————————
def require_channel_membership(channel_username: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            try:
                member = await ctx.bot.get_chat_member(
                    chat_id=channel_username,
                    user_id=update.effective_user.id
                )
            except Exception:
                return await update.message.reply_text(
                    "❌ لا يمكن التحقق من اشتراكك؛ تأكد من إضافة البوت كمسؤول."
                )
            if member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                return await func(update, ctx)
            return await update.message.reply_text(
                f"❌ يجب عليك الاشتراك في {channel_username} أولاً."
            )
        return wrapper
    return decorator

# —————————————————————————————————————————
# /start command handler
# —————————————————————————————————————————
@require_channel_membership(CHANNEL_USERNAME)
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        KeyboardButton("تيك توك"),
        KeyboardButton("يوتيوب"),
        KeyboardButton("إنستغرام"),
    ]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "👋 أهلاً! اختر المنصة التي تريد تحميل الفيديو منها:",
        reply_markup=reply_markup
    )
    user_sessions[update.effective_user.id] = None

# —————————————————————————————————————————
# Video download via yt_dlp
# —————————————————————————————————————————
async def download_video(url: str) -> Path:
    if url in cache:
        path = Path(cache[url])
        if path.exists():
            logger.info("Cache hit for %s", url)
            return path
        cache.pop(url)
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "format": "mp4[height<=720]/mp4",
        "noplaylist": True,
        "quiet": True,
    }
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(
        None,
        lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=True)
    )
    path = DOWNLOAD_DIR / f"{info['id']}.{info['ext']}"
    cache.set(url, str(path))
    return path

# —————————————————————————————————————————
# Background task: download & send
# —————————————————————————————————————————
async def process_download_and_send(url: str, chat_id: int, bot):
    try:
        video_path = await download_video(url)
        with open(video_path, "rb") as f:
            await bot.send_video(chat_id, video=f)
    except Exception as e:
        logger.exception("Background download error")
        await bot.send_message(chat_id, text=f"❌ فشل التحميل: {e}")

# —————————————————————————————————————————
# Message handler
# —————————————————————————————————————————
@require_channel_membership(CHANNEL_USERNAME)
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    txt     = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Platform selection
    if txt in ("تيك توك", "يوتيوب", "إنستغرام") and uid in user_sessions:
        user_sessions[uid] = txt
        return await update.message.reply_text(f"✅ اخترت {txt}. الآن أرسل الرابط:")

    # Ensure platform was chosen
    if uid not in user_sessions or not user_sessions[uid]:
        return await update.message.reply_text("⇨ لازم تختار المنصة أولاً بإرسال /start")

    url = txt

    # Acknowledge and start download in background
    await update.message.reply_text("⏳ جاري التحميل في الخلفية، سأرسله لك عند الانتهاء…")
    asyncio.create_task(process_download_and_send(url, chat_id, ctx.bot))

    # Reset session for next use
    user_sessions.pop(uid, None)

# —————————————————————————————————————————
# Entry point
# —————————————————————————————————————————
if __name__ == "__main__":
    # Start Flask keep-alive server
    keep_alive()

    async def on_startup(app):
        await app.bot.set_my_commands([BotCommand("start", "ابدأ البوت")])

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(on_startup)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Bot is running...")
    app.run_polling()
