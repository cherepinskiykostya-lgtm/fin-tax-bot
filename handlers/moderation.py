import logging
from typing import Optional
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from settings import settings
from db.session import SessionLocal
from db.models import Article, Draft

log = logging.getLogger("bot")

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if not uid or uid not in settings.admin_id_list:
            try:
                if update.message:
                    await update.message.reply_text("Доступ заборонено.")
            except Exception:
                pass
            return
        return await func(update, context)
    return wrapper


@admin_only
async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показать 5 последних драфтов на модерации.
    """
    async with SessionLocal() as s:  # type: AsyncSession
        rows = (
            await s.execute(
                select(Draft)
                .where(
                    or_(
                        Draft.approved.is_(False),
                        Draft.approved.is_(None),
                    )
                )
                .order_by(Draft.id.desc())
                .limit(5)
            )
        ).scalars().all()
    if not rows:
        await update.message.reply_text("Черга порожня.")
        return
    text = "Останні драфти (неопубліковані):\n"
    for d in rows:
        text += f"- ID {d.id} (article {d.article_id})\n"
    await update.message.reply_text(text)


@admin_only
async def preview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /preview <draft_id>
    """
    if not context.args:
        await update.message.reply_text("Використання: /preview <id>")
        return
    try:
        did = int(context.args[0])
    except Exception:
        await update.message.reply_text("Некоректний ID.")
        return

    async with SessionLocal() as s:
        d: Optional[Draft] = await s.get(Draft, did)
    if not d:
        await update.message.reply_text("Драфт не знайдено.")
        return

    caption = d.body_md + "\n\n" + d.sources_md + "\n\n" + d.tags
    if d.image_url:
        try:
            await update.message.reply_photo(d.image_url, caption=caption, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(caption, parse_mode="Markdown")
    else:
        await update.message.reply_text(caption, parse_mode="Markdown")


@admin_only
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /approve <draft_id> — публикует в канал и помечает approved
    Контроль: хотя бы один source из Рівень 1.
    """
    if not context.args:
        await update.message.reply_text("Використання: /approve <id>")
        return
    try:
        did = int(context.args[0])
    except Exception:
        await update.message.reply_text("Некоректний ID.")
        return

    async with SessionLocal() as s:
        d: Optional[Draft] = await s.get(Draft, did)
        if not d:
            await update.message.reply_text("Драфт не знайдено.")
            return
        a: Optional[Article] = await s.get(Article, d.article_id)
        if not a:
            await update.message.reply_text("Статтю не знайдено.")
            return

        # Проверка «Рівень 1»
        if not a.level1_ok:
            await update.message.reply_text("Відхилено: немає офіційного джерела (Рівень 1).")
            return

        # Паблиш в канал
        caption = d.body_md + "\n\n" + d.sources_md + "\n\n" + d.tags
        try:
            if d.image_url:
                await context.bot.send_photo(chat_id=settings.CHANNEL_ID, photo=d.image_url, caption=caption, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=settings.CHANNEL_ID, text=caption, parse_mode="Markdown")
        except Exception as e:
            log.exception("send to channel failed: %s", e)
            await update.message.reply_text("Не вдалося відправити в канал.")
            return

        d.approved = True
        await s.merge(d)
        await s.commit()

    await update.message.reply_text("Опубліковано ✅")
