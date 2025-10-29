from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict

from sqlalchemy import select

from db.migrations import ensure_llm_raw_column
from db.models import Article, Draft, DraftPreview
from db.session import SessionLocal
from handlers.draft_make import SUBSCRIBE_PROMO_MD
from services.post_sections import split_post_sections
from services.previews import build_preview_variants
from services.text_cleanup import rebuild_draft_body_md, strip_redundant_preamble
from services.tax_urls import tax_canonical_url

log = logging.getLogger("jobs.cleanup_drafts")


def _extract_first_url(sources_md: str | None) -> str | None:
    if not sources_md:
        return None
    match = re.search(r"\((https?://[^)\s]+)\)", sources_md)
    if match:
        return match.group(1)
    return None


def _rebuild_long_post(raw_text: str, title: str) -> str:
    sections = split_post_sections(raw_text)
    long_post = sections.long.strip()
    body_core = long_post or raw_text
    return strip_redundant_preamble(body_core, title)


async def cleanup_drafts() -> None:
    await ensure_llm_raw_column()

    async with SessionLocal() as session:
        result = await session.execute(
            select(Draft, Article).join(Article, Draft.article_id == Article.id)
        )
        rows = result.all()

        updated_drafts = 0
        updated_previews = 0

        for draft, article in rows:
            title = article.title or ""
            original_body = (draft.body_md or "").strip()
            subscribe_present = SUBSCRIBE_PROMO_MD in original_body
            subscribe_block = SUBSCRIBE_PROMO_MD if subscribe_present else ""

            if draft.llm_raw_md:
                cleaned_core = _rebuild_long_post(draft.llm_raw_md, title)
                segments = []
                title_block = title.strip()
                if title_block:
                    segments.append(f"**{title_block}**")
                if cleaned_core:
                    segments.append(cleaned_core)
                if subscribe_block:
                    segments.append(subscribe_block)
                rebuilt_input = "\n\n".join(segment for segment in segments if segment)
                rebuilt_body = rebuild_draft_body_md(
                    rebuilt_input,
                    title,
                    subscribe_block or None,
                )
            else:
                rebuilt_body = rebuild_draft_body_md(
                    original_body,
                    title,
                    subscribe_block or None,
                )

            if rebuilt_body and rebuilt_body != original_body:
                log.info(
                    "cleaning draft_id=%s article_id=%s", draft.id, draft.article_id
                )
                draft.body_md = rebuilt_body
                updated_drafts += 1

            link_url = _extract_first_url(draft.sources_md) or tax_canonical_url(article.url) or article.url or ""

            try:
                preview_variants: Dict[str, str] = build_preview_variants(
                    title=title,
                    review_md=draft.body_md,
                    link_url=link_url,
                    tags=draft.tags or "",
                )
            except Exception as exc:
                log.warning(
                    "failed to rebuild previews draft_id=%s: %s", draft.id, exc
                )
                continue

            preview_rows = (
                await session.execute(
                    select(DraftPreview).where(DraftPreview.draft_id == draft.id)
                )
            ).scalars().all()

            by_kind = {p.kind: p for p in preview_rows}
            for kind, text in preview_variants.items():
                text = text.strip()
                existing = by_kind.get(kind)
                if existing:
                    if existing.text_md.strip() != text:
                        existing.text_md = text
                        updated_previews += 1
                else:
                    session.add(
                        DraftPreview(
                            draft_id=draft.id,
                            kind=kind,
                            text_md=text,
                        )
                    )
                    updated_previews += 1

        await session.commit()

    log.info(
        "draft cleanup finished: %s drafts updated, %s previews refreshed",
        updated_drafts,
        updated_previews,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(cleanup_drafts())


if __name__ == "__main__":
    main()
