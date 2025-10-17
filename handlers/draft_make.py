import logging
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
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
    except Exception as exc:
        log.warning("llm rewrite failed, fallback to original text: %s", exc)
        return text[:900]

@admin_only
async def make_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /make <article_id> — создаёт драфт с рерайтом UA и шаблоном; соблюдает правило Рівень 1.
    """
    if not context.args:
        await update.message.reply_text("Використання: /make <article_id>")
        return
    try:
        aid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Некоректний ID.")
        return

    uid = update.effective_user.id if update.effective_user else None
    log.info("make_cmd requested by %s for article_id=%s", uid, aid)

    async with SessionLocal() as s:  # type: AsyncSession
        a = await s.get(Article, aid)
        if not a:
            log.warning("article not found for draft creation: id=%s", aid)
            await update.message.reply_text("Статтю не знайдено.")
            return

        # Строгая политка: нужен уровень 1
        if not a.level1_ok:
            log.info("article level1 check failed for id=%s", aid)
            await update.message.reply_text("Відхилено: джерело не входить до Рівень 1.")
            return

        # Готовим ввод для LLM
        base_text = f"{a.title}\n\n{(a.summary or '')}\n\n{a.url}"
        ua = await _llm_rewrite_ua(PROMPT + base_text)

        # Собираем блок «Джерела» и теги
        src_md = f"Джерела: [{a.source_domain}]({_utm(a.url)})\n\n_{DISCLAIMER}_"
        tags = TAGS

        d = Draft(
            article_id=a.id,
            body_md=ua.strip(),
            sources_md=src_md,
            tags=tags,
            image_url=a.image_url,
            created_by=update.effective_user.id if update.effective_user else None,
        )
        s.add(d)
        a.taken = True
        await s.commit()
        await s.refresh(d)
        log.info(
            "draft created id=%s for article=%s by user=%s", d.id, a.id, uid
        )

    await update.message.reply_text(f"Драфт створено ✅  ID: {d.id}. Використай /preview {d.id} або /approve {d.id}")
