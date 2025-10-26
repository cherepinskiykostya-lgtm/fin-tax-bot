import logging
from typing import Optional, Dict, List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from sqlalchemy import select, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from settings import settings
from db.session import SessionLocal
from db.models import Article, Draft, DraftPreview
from jobs.fetch import run_ingest_cycle
from services.previews import (
    build_preview_variants,
    PREVIEW_WITH_IMAGE,
    PREVIEW_WITHOUT_IMAGE,
)
from services.utm import with_utm

log = logging.getLogger("bot")


async def _ensure_preview_variants(
    session: AsyncSession,
    draft: Draft,
    article: Article,
) -> Dict[str, str]:
    """Guarantee that both preview variants exist and return them."""
    previews = (
        await session.execute(
            select(DraftPreview).where(DraftPreview.draft_id == draft.id)
        )
    ).scalars().all()

    preview_map = {p.kind: p for p in previews}
    required = {PREVIEW_WITH_IMAGE, PREVIEW_WITHOUT_IMAGE}

    if not required.issubset(preview_map.keys()):
        variants = build_preview_variants(
            title=article.title,
            review_md=draft.body_md,
            link_url=with_utm(article.url),
            tags=draft.tags,
        )
        for kind, text in variants.items():
            if kind in preview_map:
                preview_map[kind].text_md = text
            else:
                preview = DraftPreview(draft_id=draft.id, kind=kind, text_md=text)
                session.add(preview)
                preview_map[kind] = preview
        await session.flush()

    return {kind: obj.text_md for kind, obj in preview_map.items()}


async def _send_variant_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    text: str,
    image_url: Optional[str],
    as_photo: bool,
) -> None:
    normalized_image_url = image_url.strip() if image_url else ""
    if as_photo and normalized_image_url:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=normalized_image_url,
            caption=text,
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )

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

    previews: Dict[str, str] = {}

    async with SessionLocal() as s:
        d: Optional[Draft] = await s.get(Draft, did)
        if not d:
            log.warning("preview_cmd: draft not found id=%s", did)
            await update.message.reply_text("Драфт не знайдено.")
            return

        a: Optional[Article] = await s.get(Article, d.article_id)
        if not a:
            log.warning("preview_cmd: article missing for draft id=%s article_id=%s", did, d.article_id)
            await update.message.reply_text("Статтю не знайдено.")
            return

        previews = await _ensure_preview_variants(s, d, a)

    preview_with_image = previews.get(PREVIEW_WITH_IMAGE)
    preview_without_image = previews.get(PREVIEW_WITHOUT_IMAGE)

    has_image = bool((d.image_url or "").strip())

    buttons: list[list[InlineKeyboardButton]] = []
    if preview_with_image:
        buttons.append(
            [
                InlineKeyboardButton(
                    "👁️ Прев'ю з картинкою (до 1024)",
                    callback_data=f"draft:{d.id}:show:{PREVIEW_WITH_IMAGE}",
                )
            ]
        )

    if preview_without_image:
        buttons.append(
            [
                InlineKeyboardButton(
                    "👁️ Прев'ю без картинки (до 4096)",
                    callback_data=f"draft:{d.id}:show:{PREVIEW_WITHOUT_IMAGE}",
                )
            ]
        )

    if preview_with_image and has_image:
        buttons.append(
            [
                InlineKeyboardButton(
                    "✅ Опублікувати з картинкою",
                    callback_data=f"draft:{d.id}:publish:{PREVIEW_WITH_IMAGE}",
                )
            ]
        )

    if preview_without_image:
        buttons.append(
            [
                InlineKeyboardButton(
                    "✅ Опублікувати без картинки",
                    callback_data=f"draft:{d.id}:publish:{PREVIEW_WITHOUT_IMAGE}",
                )
            ]
        )

    keyboard = InlineKeyboardMarkup(buttons)

    intro_lines = [f"Драфт {d.id}: доступні варіанти прев'ю."]
    if preview_with_image:
        if has_image:
            intro_lines.append("З картинкою — все повідомлення має вміститись у 1024 символи.")
        else:
            intro_lines.append("Короткий варіант до 1024 символів доступний без збереженої картинки.")
    if preview_without_image:
        intro_lines.append("Без картинки — можна використати до 4096 символів.")
    intro_lines.append(
        "Скористайся кнопками нижче, щоб переглянути або опублікувати обраний формат."
    )

    if update.message:
        await update.message.reply_text("\n".join(intro_lines), reply_markup=keyboard)


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

        if not a.level1_ok:
            log.info("approve_cmd: level1 check failed for draft=%s article=%s", did, a.id)
            await update.message.reply_text("Відхилено: немає офіційного джерела (Рівень 1).")
            return

        previews = await _ensure_preview_variants(s, d, a)

        has_image = bool((d.image_url or "").strip())
        variant = PREVIEW_WITH_IMAGE if has_image else PREVIEW_WITHOUT_IMAGE
        if len(context.args) > 1:
            option = context.args[1].lower()
            if option in {"img", "image", "photo", "with", "with_image", "pic", "фото", "картинка"}:
                variant = PREVIEW_WITH_IMAGE
            elif option in {"text", "noimage", "without", "without_image", "plain", "без", "текст"}:
                variant = PREVIEW_WITHOUT_IMAGE

        if variant == PREVIEW_WITH_IMAGE and not has_image:
            variant = PREVIEW_WITHOUT_IMAGE

        text = previews.get(variant)
        if not text:
            await update.message.reply_text("Не знайдено збережений варіант для публікації.")
            return

        prefer_photo = variant == PREVIEW_WITH_IMAGE and has_image

        try:
            await _send_variant_to_chat(
                context,
                settings.CHANNEL_ID,
                text=text,
                image_url=d.image_url,
                as_photo=prefer_photo,
            )
        except Exception as e:
            log.exception("send to channel failed: %s", e)
            await update.message.reply_text("Не вдалося відправити в канал.")
            return

        d.approved = True
        await s.merge(d)
        await s.commit()
        log.info("approve_cmd: draft=%s published by %s as %s", did, uid, variant)

    await update.message.reply_text("Опубліковано ✅")


@admin_only
async def draft_preview_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer("Некоректна дія.", show_alert=True)
        return

    _, draft_id_raw, action, variant = parts

    if variant not in {PREVIEW_WITH_IMAGE, PREVIEW_WITHOUT_IMAGE}:
        await query.answer("Невідомий варіант.", show_alert=True)
        return

    try:
        draft_id = int(draft_id_raw)
    except ValueError:
        await query.answer("Некоректний ID.", show_alert=True)
        return

    async with SessionLocal() as s:
        draft: Optional[Draft] = await s.get(Draft, draft_id)
        if not draft:
            await query.answer("Драфт не знайдено.", show_alert=True)
            return

        article: Optional[Article] = await s.get(Article, draft.article_id)
        if not article:
            await query.answer("Статтю не знайдено.", show_alert=True)
            return

        previews = await _ensure_preview_variants(s, draft, article)
        text = previews.get(variant)
        if not text:
            await query.answer("Варіант відсутній.", show_alert=True)
            return
        has_image = bool((draft.image_url or "").strip())
        prefer_photo = variant == PREVIEW_WITH_IMAGE and has_image

        if action == "show":
            await query.answer("Надсилаю прев'ю…", show_alert=False)
            target_chat_id: Optional[int] = None
            if query.message and query.message.chat_id:
                target_chat_id = query.message.chat_id
            elif update.effective_chat:
                target_chat_id = update.effective_chat.id

            if target_chat_id is None:
                log.warning("draft_preview_action_callback: unable to resolve chat for preview draft_id=%s", draft_id)
                return

            await _send_variant_to_chat(
                context,
                target_chat_id,
                text=text,
                image_url=draft.image_url,
                as_photo=prefer_photo,
            )
            return

        if action == "publish":
            try:
                await _send_variant_to_chat(
                    context,
                    settings.CHANNEL_ID,
                    text=text,
                    image_url=draft.image_url,
                    as_photo=prefer_photo,
                )
            except Exception as exc:
                log.exception("draft_preview_action_callback publish failed: %s", exc)
                await query.answer("Не вдалося опублікувати.", show_alert=True)
                return

            draft.approved = True
            await s.merge(draft)
            await s.commit()

            await query.answer("Опубліковано ✅", show_alert=False)
            if query.message:
                await query.message.reply_text("Опубліковано ✅")
            return

    await query.answer("Невідома дія.", show_alert=True)


@admin_only
async def articles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать последние собранные статьи (по умолчанию только свободные)."""

    limit = 20
    if context.args:
        try:
            parsed = int(context.args[0])
            limit = max(1, min(parsed, 100))
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
    max_message_length = 4000
    current_lines: List[str] = []
    current_length = 0

    for line in lines:
        line_length = len(line)
        # Account for newline that will be inserted when joining.
        extra_length = 1 if current_lines else 0
        if current_length + extra_length + line_length > max_message_length:
            await update.message.reply_text("\n".join(current_lines))
            current_lines = [line]
            current_length = line_length
        else:
            if extra_length:
                current_length += extra_length
            current_lines.append(line)
            current_length += line_length

    if current_lines:
        await update.message.reply_text("\n".join(current_lines))


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
