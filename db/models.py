from datetime import datetime
from typing import Optional, Literal

from sqlalchemy import String, BigInteger, Integer, Text, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .session import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))
    last_name: Mapped[Optional[str]] = mapped_column(String(64))
    language_code: Mapped[Optional[str]] = mapped_column(String(8))


# Темы из ТЗ как «machine tags» для авто-тегов
Topic = Literal[
    "PillarTwo", "CFC", "CRS", "BO", "TP", "WHT", "IPBox", "HOLDING", "UA_TAX", "NBU", "DiiaCity", "CASELAW", "PRACTICE"
]

class Article(Base):
    """
    Сырые статьи, собранные из RSS/GoogleNews.
    """
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    source_domain: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    level1_ok: Mapped[bool] = mapped_column(Boolean, default=False)  # домен в бел-листе lvl1
    topics: Mapped[Optional[str]] = mapped_column(String(255))  # csv из Topic
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    taken: Mapped[bool] = mapped_column(Boolean, default=False)  # уже создан драфт под эту статью


class Draft(Base):
    """
    Драфт поста на модерации.
    """
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(Integer)
    # Сгенерированный текст UA 600–900 символів (без лінків)
    body_md: Mapped[str] = mapped_column(Text)
    # список ссылок/источников (с UTM). Храним как простой текст csv/строки.
    sources_md: Mapped[str] = mapped_column(Text)
    # финальные хэштеги вида "#PillarTwo #CFC ..."
    tags: Mapped[str] = mapped_column(String(255))
    # превью картинки
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)  # admin ID кто инициировал
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DraftPreview(Base):
    """Збережені варіанти прев'ю для драфтів."""

    __tablename__ = "draft_previews"
    __table_args__ = (UniqueConstraint("draft_id", "kind", name="uq_draft_preview_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    text_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
