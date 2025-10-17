from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import ContextTypes
from db.session import SessionLocal
from db.models import User


MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/articles"), KeyboardButton("/queue")],
        [KeyboardButton("/preview"), KeyboardButton("/approve")],
        [KeyboardButton("/make"), KeyboardButton("/help")],
        [KeyboardButton("/ping")],
    ],
    resize_keyboard=True,
)


BOT_COMMANDS = [
    BotCommand("start", "Запустить бота"),
    BotCommand("help", "Справка по командам"),
    BotCommand("ping", "Проверка доступности"),
    BotCommand("articles", "Показать свежие статьи"),
    BotCommand("queue", "Показать очередь драфтов"),
    BotCommand("preview", "Показать драфт по ID"),
    BotCommand("approve", "Опубликовать драфт"),
    BotCommand("make", "Создать новую задачу"),
]

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
    if update.message:
        await update.message.reply_text(
            "Привет! Бот на Railway готов 🚀  Команды доступны в меню.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Команды:\n"
        "/start — начать\n"
        "/help — помощь\n"
        "/ping — проверка\n"
        "/articles [N|all] — свежие статьи\n"
        "/queue — очередь драфтов\n"
        "/preview <id> — предпросмотр драфта\n"
        "/approve <id> — публикация драфта\n"
        "/make — создать задачу"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=MAIN_MENU_KEYBOARD)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("pong ✅", reply_markup=MAIN_MENU_KEYBOARD)
