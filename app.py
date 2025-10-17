import logging
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from settings import settings
from handlers.base import start, help_cmd, ping

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

app = FastAPI(title="Telegram Bot on Railway")

# --- Telegram Application ---
tg_app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

# --- Scheduler ---
scheduler = AsyncIOScheduler(timezone=settings.CRON_TZ)

async def scheduled_job():
    log.info("Scheduled job tick")

# --- Проверка доступа (декоратор) ---
def admin_only(handler_func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or user_id not in settings.ADMIN_IDS:
            log.warning(f"⛔️ Access denied for user {user_id}")
            try:
                await update.message.reply_text("Доступ запрещён.")
            except Exception:
                pass
            return
        return await handler_func(update, context)
    return wrapper

# --- Обработчики команд только для админов ---
tg_app.add_handler(CommandHandler("start", admin_only(start)))
tg_app.add_handler(CommandHandler("help", admin_only(help_cmd)))
tg_app.add_handler(CommandHandler("ping", admin_only(ping)))

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
    await tg_app.initialize()
    await tg_app.start()

    scheduler.add_job(scheduled_job, CronTrigger(minute="*/10"))
    scheduler.start()

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
