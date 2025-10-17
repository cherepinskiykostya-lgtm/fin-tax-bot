import logging
import asyncio
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

tg_app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("ping", ping))

scheduler = AsyncIOScheduler(timezone=settings.CRON_TZ)

async def scheduled_job():
    log.info("Scheduled job tick")

@app.post(f"/webhook/{settings.WEBHOOK_SECRET}")
async def tg_webhook(request: Request):
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="Unsupported Media Type")
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/healthz")
async def health():
    return {"status": "ok"}

@app.on_event("startup")
async def on_startup():
    scheduler.add_job(scheduled_job, CronTrigger(minute="*/10"))
    scheduler.start()
    if settings.BASE_URL:
        url = f"{settings.BASE_URL}/webhook/{settings.WEBHOOK_SECRET}"
        await tg_app.bot.set_webhook(url)
        log.info("Webhook set to %s", url)
    else:
        log.warning("BASE_URL не задан — вебхук не установлен")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
