import asyncio
import logging
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from handlers.moderation import queue_cmd, preview_cmd, approve_cmd, articles_cmd
from handlers.draft_make import make_cmd
from jobs.fetch import run_ingest_cycle
from db import init_models


from settings import settings
from handlers.base import start, help_cmd, ping, BOT_COMMANDS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

app = FastAPI(title="Telegram Bot on Railway")

# --- Telegram Application ---
tg_app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
_tg_event_loop: asyncio.AbstractEventLoop | None = None

# --- Scheduler ---
scheduler = AsyncIOScheduler(timezone=settings.CRON_TZ)

async def scheduled_job():
    log.info("Scheduled job tick")

# --- Проверка доступа (декоратор) ---
def admin_only(handler_func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        admin_ids = settings.admin_id_list
        if not user_id or user_id not in admin_ids:
            log.warning(f"⛔️ Access denied for user {user_id} (admins={admin_ids})")
            try:
                if update.message:
                    await update.message.reply_text("Доступ запрещён.")
                elif update.callback_query:
                    await update.callback_query.answer("Доступ запрещён.", show_alert=True)
            except Exception:
                pass
            return
        return await handler_func(update, context)
    return wrapper

# --- Обработчики команд только для админов ---
tg_app.add_handler(CommandHandler("start", admin_only(start)))
tg_app.add_handler(CommandHandler("help", admin_only(help_cmd)))
tg_app.add_handler(CommandHandler("ping", admin_only(ping)))
tg_app.add_handler(CommandHandler("articles", articles_cmd))
tg_app.add_handler(CommandHandler("queue", queue_cmd))
tg_app.add_handler(CommandHandler("preview", preview_cmd))
tg_app.add_handler(CommandHandler("approve", approve_cmd))
tg_app.add_handler(CommandHandler("make", make_cmd))

# --- Webhook endpoint ---
@app.post(f"/webhook/{settings.WEBHOOK_SECRET}")
async def tg_webhook(request: Request):
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="Unsupported Media Type")
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# --- Healthcheck ---
@app.get("/healthz")
async def health():
    return {"status": "ok"}

# --- Lifecycle: startup/shutdown ---
@app.on_event("startup")
async def on_startup():
    global _tg_event_loop
    await tg_app.initialize()
    await tg_app.start()

    await init_models()
    log.info("Database schema ensured")

    await tg_app.bot.set_my_commands(BOT_COMMANDS)
    log.info("Bot commands menu initialized")

    _tg_event_loop = asyncio.get_running_loop()

    # ЛОГ: показываем, каких админов увидели из переменных окружения
    log.info("Admin IDs loaded: %s", settings.admin_id_list)

    scheduler.add_job(scheduled_job, CronTrigger(minute="*/10"))
    scheduler.start()
    scheduler.add_job(_schedule_ingest_cycle, CronTrigger(minute="*/30"))
    _schedule_ingest_cycle()

    if settings.BASE_URL:
        url = f"{settings.BASE_URL}/webhook/{settings.WEBHOOK_SECRET}"
        await tg_app.bot.set_webhook(url, drop_pending_updates=True)
        log.info("Webhook set to %s", url)
    else:
        log.warning("BASE_URL не задан — вебхук не установлен")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass

    try:
        await tg_app.stop()
        await tg_app.shutdown()
    except Exception:
        pass

    global _tg_event_loop
    _tg_event_loop = None


def _schedule_ingest_cycle():
    """Schedule ingest cycle on the Telegram application's event loop."""
    if not _tg_event_loop or _tg_event_loop.is_closed():
        log.warning("Cannot schedule ingest cycle – Telegram loop is unavailable")
        return

    try:
        asyncio.run_coroutine_threadsafe(run_ingest_cycle(), _tg_event_loop)
    except RuntimeError:
        log.exception("Failed to dispatch ingest cycle task")
