import os


def url() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        # локально/по умолчанию — SQLite
        return "sqlite+aiosqlite:///./app.db"

    # Normalize schemes from Railway/heroku-style
    # 1) postgres:// → postgresql://
    dsn = dsn.replace("postgres://", "postgresql://", 1)

    # 2) если нет явного драйвера, добавим +asyncpg
    if "postgresql+asyncpg://" not in dsn and "postgresql+psycopg" not in dsn:
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

    return dsn


async def init_models() -> None:
    """Ensure that all ORM models have backing tables in the database."""
    from .session import Base, engine  # local import to avoid circular dependency

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
