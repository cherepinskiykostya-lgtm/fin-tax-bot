from telegram import Update
from telegram.ext import ContextTypes
from db.session import SessionLocal
from db.models import User

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        try:
            async with SessionLocal() as session:
                await session.run_sync(lambda sync_conn: User.metadata.create_all(sync_conn))
                existing = await session.get(User, update.effective_user.id)
                if not existing:
                    session.add(User(
                        id=update.effective_user.id,
                        username=update.effective_user.username,
                        first_name=update.effective_user.first_name,
                        last_name=update.effective_user.last_name,
                        language_code=update.effective_user.language_code,
                    ))
                await session.commit()
        except Exception:
            pass
    await update.message.reply_text("Привет! Бот на Railway готов 🚀  /help — список команд")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Команды:\n/start — начать\n/help — помощь\n/ping — проверка"
    await update.message.reply_text(text)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")
