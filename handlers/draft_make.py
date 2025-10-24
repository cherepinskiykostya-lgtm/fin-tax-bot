import logging
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from settings import settings
from db.session import SessionLocal
from db.models import Article, Draft, DraftPreview
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


TAGS = "#PillarTwo #CFC #CRS #BO #WHT #IPBox #TP #DiiaCity #NBU #UkraineTax #IT"
DISCLAIMER = "Матеріал має інформативний характер і не є податковою/юридичною консультацією."

PROMPT = """Ти редактор новин з міжнародного оподаткування. Розгорнуто (1200–2000 символів українською) сформуй повідомлення для Telegram за шаблоном Markdown:
🧭 [ТЕМА] Країна/Орган — коротко
Що сталося: 1–2 речення.
Чому важливо (IT/CFO): 1–2 буліти.
Що зробити: 1–3 буліти.
Наприкінці не додавай посилання та теги, тільки текст повідомлення. Тон: нейтрально-експертний, без юрпорад. Ось вихідні дані (заголовок, короткий зміст, URL): 
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

        # Готовим ввод для LLM
        base_text = f"{a.title}\n\n{(a.summary or '')}\n\n{a.url}"
        ua = await _llm_rewrite_ua(PROMPT, base_text)

        ua = ua.strip()
        if "Чому важливо (IT/CFO):" in ua:
            lines = []
            for line in ua.splitlines():
                if line.startswith("Чому важливо (IT/CFO):") and lines and lines[-1] != "":
                    lines.append("")
                lines.append(line)
            ua = "\n".join(lines).strip()

        title_line = f"**{a.title.strip()}**"
        body_md = f"{title_line}\n\n{ua}" if ua else title_line

        # Собираем блок «Джерела» и теги
        link_with_utm = with_utm(a.url)
        src_md = f"Джерела: [{a.source_domain}]({link_with_utm})\n\n_{DISCLAIMER}_"
        tags = TAGS

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
