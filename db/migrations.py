from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .session import engine

log = logging.getLogger("db.migrations")


async def ensure_llm_raw_column() -> None:
    """Make sure drafts table contains the llm_raw_md column."""

    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE drafts ADD COLUMN llm_raw_md TEXT"))
            log.info("added llm_raw_md column to drafts table")
        except DBAPIError as exc:  # column may already exist
            message = str(getattr(exc, "orig", exc)).lower()
            if "duplicate column" in message or "already exists" in message:
                log.debug("llm_raw_md column already present: %s", message)
                return
            raise
