import os

def url() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        # локально/по-умолчанию — SQLite
        return "sqlite+aiosqlite:///./app.db"

    # Railway может отдавать и postgres:// и postgresql://
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgresql://") and "+asyncpg://" not in dsn:
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

    return dsn
