#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# tik.py

import os
import logging
import asyncio
from pathlib import Path
from functools import wraps

from telegram import Update, ChatMember, BotCommand
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

# تحميل المتغيرات من ملف .env
load_dotenv()

# —————————————————————————————————————————————————————————
# CONFIGURATION
# —————————————————————————————————————————————————————————
TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
DOWNLOAD_DIR   = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
CACHE_DIR      = Path(os.getenv("CACHE_DIR", "cache"))
MAX_CACHE_SIZE = int(os.getenv("MAX_CACHE_SIZE", "1000000000"))  # 1 GB

# ضع اسم قناتك هنا، مع علامة @
CHANNEL_USERNAME = "@redotpaylfiicial"

# —————————————————————————————————————————————————————————
# LOGGER
# —————————————————————————————————————————————————————————
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s ▶ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# —————————————————————————————————————————————————————————
# CACHE FOR AVOIDING REDOWNLOADS
# —————————————————————————————————————————————————————————
cache = diskcache.Cache(str(CACHE_DIR), size_limit=MAX_CACHE_SIZE)

# —————————————————————————————————————————————————————————
# HELPER DECORATORS
# —————————————————————————————————————————————————————————
def require_channel_membership(channel_username: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            try:
                member = await ctx.bot.get_chat_member(
                    chat_id=channel_username,
                    user_id=user_id
                )
            except Exception:
                return await update.message.reply_text(
                    "❌ لا يمكن التحقق من اشتراكك، تأكّد من إضافة البوت كمسؤول في القناة."
                )

            if member.status in (
                ChatMember.MEMBER,
                ChatMember.ADMINISTRATOR,
                ChatMember.OWNER
            ):
                return await func(update, ctx)
            else:
                return await update.message.reply_text(
                    f"❌ يجب عليك الاشتراك في {channel_username} أولاً."
                )
        return wrapper
    return decorator

def send_typing(func):
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await ctx.bot.send_chat_action(update.effective_chat.id, "upload_video")
        return await func(update, ctx)
    return wrapper

# —————————————————————————————————————————————————————————
# /start COMMAND
# —————————————————————————————————————————————————————————
@require_channel_membership(CHANNEL_USERNAME)
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو (YouTube, TikTok, Instagram...) وسأرسله لك بدون علامة مائية."
    )

# —————————————————————————————————————————————————————————
# DOWNLOAD & CACHE LOGIC
# —————————————————————————————————————————————————————————
async def download_video(url: str) -> Path:
    if url in cache:
        path = Path(cache[url])
        if path.exists():
            logger.info("Cache hit for %s", url)
            return path
        cache.pop(url, None)

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    outtmpl = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "mp4[height<=720]/mp4",
        "noplaylist": True,
        "quiet": True,
    }
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(
        None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True)
    )
    path = DOWNLOAD_DIR / f"{info['id']}.{info['ext']}"
    cache.set(url, str(path))
    return path

# —————————————————————————————————————————————————————————
# MESSAGE HANDLER
# —————————————————————————————————————————————————————————
@require_channel_membership(CHANNEL_USERNAME)
@send_typing
async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    # 1) تنزيل أو جلب من الكاش
    try:
        video_path = await download_video(url)
    except Exception:
        logger.exception("Download error")
        return await update.message.reply_text("لا يمكن تحميل هذا الفيديو")

    # 2) إرسال الفيديو مع إعادة محاولة بسيطة على Timeout
    try:
        with open(video_path, "rb") as f:
            try:
                await ctx.bot.send_video(chat_id, video=f)
            except Exception as e:
                msg = type(e).__name__.lower()
                if "timeout" in msg or "readtimeout" in msg:
                    logger.warning("Timeout on first send, retrying…")
                    f.seek(0)
                    await ctx.bot.send_video(chat_id, video=f)
                else:
                    raise
    except Exception:
        logger.exception("Send error")
        await update.message.reply_text("أنتظر قليلا سيتم إرسال الفيديو")

# —————————————————————————————————————————————————————————
# MAIN ENTRYPOINT
# —————————————————————————————————————————————————————————
if __name__ == "__main__":
    async def on_startup(app):
        # إعداد قائمة الأوامر الظاهرة في زر القائمة الثلاثية
        await app.bot.set_my_commands([
            BotCommand("start", "ابدأ البوت")
        ])

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(on_startup)
        .build()
    )
    # ربط الرسائل المحتوية على http:// أو https:// بالدالة handle_link
    app.add_handler(
        MessageHandler(
            filters.Regex(r"https?://\S+"),
            handle_link
        )
    )
    app.add_handler(CommandHandler("start", start))
    logger.info("Bot is starting...")
    app.run_polling()
