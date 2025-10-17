import logging
from typing import Iterable, Tuple
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

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


TAGS = "#PillarTwo #CFC #CRS #BO #WHT #IPBox #TP #DiiaCity #NBU #UkraineTax #IT"
DISCLAIMER = "Матеріал має інформативний характер і не є податковою/юридичною консультацією."

PROMPT = """Ти редактор новин з міжнародного оподаткування. Стисло (600–900 символів українською) сформуй повідомлення для Telegram за шаблоном Markdown:
🧭 [ТЕМА] Країна/Орган — коротко
Що сталося: 1–2 речення.
Чому важливо (IT/CFO): 1–2 буліти.
Що зробити: 1–3 буліти.
Наприкінці не додавай посилання та теги, тільки текст повідомлення. Тон: нейтрально-експертний, без юрпорад. Ось вихідні дані (заголовок, короткий зміст, URL): 
"""

def _utm(url: str) -> str:
    params = {"utm_source": settings.UTM_SOURCE, "utm_medium": settings.UTM_MEDIUM, "utm_campaign": settings.UTM_CAMPAIGN}
    glue = "&" if ("?" in url) else "?"
    return url + glue + urlencode(params)

async def _llm_rewrite_ua(text: str) -> str:
    if not settings.OPENAI_API_KEY:
        # фоллбек — просто вернём текст
        return text[:900]
    try:
        import openai  # type: ignore
        openai.api_key = settings.OPENAI_API_KEY
        # совместимо со старым SDK
        completion = openai.ChatCompletion.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a tax news editor writing concise Ukrainian summaries."},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
        )
        return completion.choices[0].message["content"][:1200]
    except Exception:
        return text[:900]

def _trim(text: str, limit: int = 48) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def _fetch_article_candidates(limit: int = 6) -> list[Article]:
    async with SessionLocal() as s:  # type: AsyncSession
        rows = (
            await s.execute(
                select(Article)
                .where(Article.level1_ok.is_(True), Article.taken.is_(False))
                .order_by(Article.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return list(rows)


def _build_keyboard(articles: Iterable[Article]) -> Tuple[str, InlineKeyboardMarkup]:
    rows = []
    articles = list(articles)
    if articles:
        for a in articles:
            domain = _trim(a.source_domain, 18)
            title = _trim(a.title or a.url, 32)
            text = f"{domain} · {title}"
            rows.append([InlineKeyboardButton(text, callback_data=f"make:{a.id}")])
        footer = [
            InlineKeyboardButton("🔄 Оновити", callback_data="make:refresh"),
            InlineKeyboardButton("✖️ Закрити", callback_data="make:close"),
        ]
        rows.append(footer)
        message = "Оберіть статтю з рівня 1, щоб зібрати драфт:"
    else:
        rows.append([InlineKeyboardButton("🔄 Оновити", callback_data="make:refresh")])
        message = "Вільних статей з рівня 1 поки немає. Оновіть трохи згодом."
    return message, InlineKeyboardMarkup(rows)


async def _send_article_menu(update: Update, *, edit_message: bool = False):
    articles = await _fetch_article_candidates()
    text, keyboard = _build_keyboard(articles)
    if edit_message and update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard)


async def _create_draft(aid: int, user_id: int | None):
    async with SessionLocal() as s:  # type: AsyncSession
        a = await s.get(Article, aid)
        if not a:
            return False, "Статтю не знайдено."
        if not a.level1_ok:
            return False, "Відхилено: джерело не входить до Рівень 1."
        if a.taken:
            return False, "Уже є драфт з цієї статті."

        base_text = f"{a.title}\n\n{(a.summary or '')}\n\n{a.url}"
        ua = await _llm_rewrite_ua(PROMPT + base_text)

        src_md = f"Джерела: [{a.source_domain}]({_utm(a.url)})\n\n_{DISCLAIMER}_"
        d = Draft(
            article_id=a.id,
            body_md=ua.strip(),
            sources_md=src_md,
            tags=TAGS,
            image_url=a.image_url,
            created_by=user_id,
        )
        s.add(d)
        a.taken = True
        await s.commit()
        return True, d


@admin_only
async def make_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /make — показує меню доступних статей або /make <article_id> для ручного вибору.
    """
    if not context.args:
        await _send_article_menu(update)
        return
    try:
        aid = int(context.args[0])
    except Exception:
        if update.message:
            await update.message.reply_text("Некоректний ID.")
        return

    success, result = await _create_draft(aid, update.effective_user.id if update.effective_user else None)
    if update.message:
        if success:
            draft: Draft = result  # type: ignore[assignment]
            await update.message.reply_text(
                f"Драфт створено ✅  ID: {draft.id}. Використай /preview {draft.id} або /approve {draft.id}"
            )
        else:
            await update.message.reply_text(result)  # type: ignore[arg-type]


@admin_only
async def make_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    if data == "make:refresh":
        await query.answer("Оновлено")
        await _send_article_menu(update, edit_message=True)
        return
    if data == "make:close":
        await query.answer("Меню закрито")
        if query.message:
            await query.message.edit_text("Меню /make закрито. Використайте команду ще раз, щоб відкрити.")
        return
    if not data.startswith("make:"):
        return

    try:
        aid = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Некоректний вибір", show_alert=True)
        return

    await query.answer("Готуємо драфт…")
    success, result = await _create_draft(aid, update.effective_user.id if update.effective_user else None)
    if success:
        draft: Draft = result  # type: ignore[assignment]
        if query.message:
            await query.message.reply_text(
                f"Драфт створено ✅  ID: {draft.id}. Використай /preview {draft.id} або /approve {draft.id}"
            )
        await _send_article_menu(update, edit_message=True)
    else:
        await query.answer(result, show_alert=True)  # type: ignore[arg-type]
