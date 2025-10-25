import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from settings import settings
from db.session import SessionLocal
from db.models import Article, Draft, DraftPreview
from services.post_sections import split_post_sections
from services.previews import build_preview_variants
from services.utm import with_utm

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


BASE_TAGS = "#PillarTwo #CFC #CRS #BO #WHT #IPBox #TP #DiiaCity #NBU #UkraineTax #IT"
SUBSCRIBE_PROMO_MD = "[**Підпишись на IT Tax Radar**](https://t.me/ITTaxRadar)"
DISCLAIMER = "Матеріал має інформативний характер і не є податковою/юридичною консультацією."

PROMPT_TEMPLATE = """Ти редактор новин з міжнародного оподаткування. Українською сформуй повідомлення для Telegram у Markdown-форматі з трьома блоками:
Довгий пост: 1200–2000 символів, структурований текст без маркованих списків і без додаткових заголовків.
Короткий пост: стисла версія обсягом 700–750 символів.
Теги: добери релевантні хештеги.
Не додавай інші розділи чи звернення до читача, не давай порад. Тон: нейтрально-експертний, фактологічний.
Не повторюй заголовок дослівно в основному тексті — використовуй його лише як джерело фактів.
Ось базовий перелік хештегів. Залишай тільки ті, що релевантні статті, нерелевантні видаляй та за потреби додавай власні: {base_tags}
Дотримуйся структури:
Довгий пост:
...
Короткий пост:
...
Теги: #...
Ось вихідні дані (заголовок, короткий зміст, URL):
"""

MAX_REWRITE_LENGTH = 3800


async def _llm_rewrite_ua(prompt: str, article_payload: str) -> str:
    if not settings.OPENAI_API_KEY:
        # фоллбек — просто вернём текст
        return article_payload[:MAX_REWRITE_LENGTH]
    try:
        import openai  # type: ignore
        openai.api_key = settings.OPENAI_API_KEY
        # совместимо со старым SDK
        completion = openai.ChatCompletion.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a tax news editor writing structured Ukrainian summaries."},
                {"role": "user", "content": prompt + article_payload},
            ],
            temperature=0.3,
        )
        return completion.choices[0].message["content"][:MAX_REWRITE_LENGTH]
    except Exception as exc:
        log.warning("llm rewrite failed, fallback to original text: %s", exc)
        return article_payload[:MAX_REWRITE_LENGTH]

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

        summary_text = (a.summary or "").strip()
        log.info(
            "make_cmd article payload article_id=%s url=%s summary_len=%s summary_text=%s",
            a.id,
            a.url,
            len(summary_text),
            summary_text,
        )

        # Готовим ввод для LLM
        base_text = f"{a.title}\n\n{(a.summary or '')}\n\n{a.url}"
        prompt = PROMPT_TEMPLATE.format(base_tags=BASE_TAGS)
        ua = await _llm_rewrite_ua(prompt, base_text)

        ua = ua.strip()

        sections = split_post_sections(ua)
        long_post = sections.long.strip()

        tags = BASE_TAGS
        tag_line = re.search(r"^Теги:\s*(.+)$", ua, flags=re.MULTILINE)
        if tag_line:
            candidate = tag_line.group(1).strip()
            if candidate:
                normalized = candidate.replace(",", " ")
                hashtags = []
                for token in normalized.split():
                    if token.startswith("#") and token not in hashtags:
                        hashtags.append(token)
                if hashtags:
                    tags = " ".join(hashtags)
                else:
                    tags = " ".join(candidate.split())
            ua = re.sub(r"^Теги:.*$", "", ua, flags=re.MULTILINE).strip()

        body_core = long_post or ua
        title_line = f"**{a.title.strip()}**"
        body_md = f"{title_line}\n\n{body_core.strip()}" if body_core.strip() else title_line
        body_md = f"{body_md.strip()}\n\n{SUBSCRIBE_PROMO_MD}".strip()

        # Собираем блок «Джерела» и теги
        link_with_utm = with_utm(a.url)
        src_md = f"Читати далі: [{a.source_domain}]({link_with_utm})\n\n_{DISCLAIMER}_"

        d = Draft(
            article_id=a.id,
            body_md=body_md.strip(),
            sources_md=src_md,
            tags=tags,
            image_url=a.image_url,
            created_by=update.effective_user.id if update.effective_user else None,
        )
        s.add(d)
        await s.flush()

        preview_variants = build_preview_variants(
            title=a.title,
            review_md=d.body_md,
            link_url=link_with_utm,
            tags=d.tags,
        )

        for kind, text in preview_variants.items():
            s.add(
                DraftPreview(
                    draft_id=d.id,
                    kind=kind,
                    text_md=text,
                )
            )

        a.taken = True
        await s.commit()
        await s.refresh(d)
        log.info(
            "draft created id=%s for article=%s by user=%s", d.id, a.id, uid
        )

    await update.message.reply_text(f"Драфт створено ✅  ID: {d.id}. Використай /preview {d.id} або /approve {d.id}")
