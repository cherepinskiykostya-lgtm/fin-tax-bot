import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from sqlalchemy import select, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from settings import settings
from db.session import SessionLocal
from db.models import Article, Draft
from jobs.fetch import run_ingest_cycle

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
    uid = update.effective_user.id if update.effective_user else None
    log.info("queue_cmd requested by %s", uid)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Оновити новини", callback_data="refresh_news")]]
    )
    async with SessionLocal() as s:  # type: AsyncSession
        rows = (
            await s.execute(
                select(Draft, Article)
                .join(Article, Article.id == Draft.article_id)
                .where(
                    or_(
                        Draft.approved.is_(False),
                        Draft.approved.is_(None),
                    )
                )
                .order_by(Draft.id.desc())
                .limit(5)
            )
        ).all()
    if not rows:
        log.info("queue_cmd: no drafts found")
        await update.message.reply_text("Черга порожня.", reply_markup=keyboard)
        return
    text = "Останні драфти (неопубліковані):\n"
    for draft, article in rows:
        text += (
            f"- ID {draft.id} → стаття {article.id} | {article.source_domain} | "
            f"{article.title[:80]}{'…' if len(article.title) > 80 else ''}\n"
        )
    await update.message.reply_text(text, reply_markup=keyboard)


@admin_only
async def queue_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("Сканування розпочато…", show_alert=False)

    summary = await run_ingest_cycle()
    results = summary.get("results", {})
    resources = summary.get("resources", [])

    lines = ["🔄 Сканування завершено."]
    lines.append(
        "Статистика: "
        f"нових {results.get('created', 0)}, "
        f"дублікатів {results.get('duplicate', 0)}, "
        f"L1-відхилень {results.get('skipped_level1', 0)}, "
        f"помилок {results.get('error', 0)}, "
        f"старих {results.get('skipped_old', 0)}, "
        f"без дати {results.get('skipped_no_date', 0)}"
    )

    if resources:
        lines.append("Ресурси:")
        for item in resources:
            name = item.get("name", "(невідомо)")
            if item.get("available", True):
                lines.append(f"{name} - доступен - {item.get('created', 0)} новостей")
            else:
                lines.append(f"{name} - не доступен")

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Оновити новини", callback_data="refresh_news")]]
    )
    target_message = query.message
    if target_message:
        await target_message.reply_text("\n".join(lines), reply_markup=keyboard)


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

    uid = update.effective_user.id if update.effective_user else None
    log.info("preview_cmd requested by %s for draft_id=%s", uid, did)

    async with SessionLocal() as s:
        d: Optional[Draft] = await s.get(Draft, did)
    if not d:
        log.warning("preview_cmd: draft not found id=%s", did)
        await update.message.reply_text("Драфт не знайдено.")
        return

    caption = d.body_md + "\n\n" + d.sources_md + "\n\n" + d.tags
    if d.image_url:
        try:
            await update.message.reply_photo(d.image_url, caption=caption, parse_mode="Markdown")
        except Exception:
            log.exception("preview_cmd failed to send photo draft_id=%s", did)
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

    uid = update.effective_user.id if update.effective_user else None
    log.info("approve_cmd requested by %s for draft_id=%s", uid, did)

    async with SessionLocal() as s:
        d: Optional[Draft] = await s.get(Draft, did)
        if not d:
            log.warning("approve_cmd: draft not found id=%s", did)
            await update.message.reply_text("Драфт не знайдено.")
            return
        a: Optional[Article] = await s.get(Article, d.article_id)
        if not a:
            log.warning("approve_cmd: article missing for draft id=%s article_id=%s", did, d.article_id)
            await update.message.reply_text("Статтю не знайдено.")
            return

        # Проверка «Рівень 1»
        if not a.level1_ok:
            log.info("approve_cmd: level1 check failed for draft=%s article=%s", did, a.id)
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
        log.info("approve_cmd: draft=%s published by %s", did, uid)

    await update.message.reply_text("Опубліковано ✅")


@admin_only
async def articles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать последние собранные статьи (по умолчанию только свободные)."""

    limit = 10
    if context.args:
        try:
            parsed = int(context.args[0])
            limit = max(1, min(parsed, 30))
        except ValueError:
            pass

    include_taken = False
    if context.args and context.args[-1].lower() in {"all", "всі", "все"}:
        include_taken = True

    async with SessionLocal() as s:  # type: AsyncSession
        stmt = select(Article).order_by(Article.id.desc()).limit(limit)
        if not include_taken:
            stmt = stmt.where(or_(Article.taken.is_(False), Article.taken.is_(None)))
        rows = (await s.execute(stmt)).scalars().all()

    if not rows:
        await update.message.reply_text("Немає статей за заданими умовами.")
        return

    lines = ["Останні статті:"]
    for art in rows:
        status = "✅ є драфт" if art.taken else "🆕 вільна"
        lvl = "L1" if art.level1_ok else "L2"
        lines.append(
            f"- {status} | ID {art.id} | {lvl} | {art.source_domain} | "
            f"{art.title[:80]}{'…' if len(art.title) > 80 else ''}"
        )
    await update.message.reply_text("\n".join(lines))


@admin_only
async def articles_reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повністю очищає таблицю статей."""

    uid = update.effective_user.id if update.effective_user else None
    log.info("articles_reset_cmd requested by %s", uid)

    async with SessionLocal() as s:  # type: AsyncSession
        result = await s.execute(delete(Article))
        await s.commit()

    deleted = result.rowcount if result.rowcount is not None else 0
    await update.message.reply_text(f"Базу статей очищено. Видалено записів: {deleted}.")
