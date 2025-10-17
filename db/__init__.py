import os

def url() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        return "sqlite+aiosqlite:///./app.db"
    dsn = dsn.replace("postgres://", "postgresql+asyncpg://")
    return dsn
