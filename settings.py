import os
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
    ids: list[int] = []
    for p in parts:
        if not p:
            continue
        ids.append(int(p))
    return ids


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str
    BASE_URL: str | None = None
    DATABASE_URL: str | None = None
    CRON_TZ: str = "Europe/Bucharest"

    # Храним как строки (чтобы pydantic не пытался JSON-декодить)
    ADMIN_IDS_RAW: str = ""   # например: 279895144,987654321
    ADMIN_IDS: str = ""       # резервный вариант имени

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def admin_id_list(self) -> list[int]:
        # приоритет ADMIN_IDS_RAW, затем ADMIN_IDS
        primary = os.getenv("ADMIN_IDS_RAW", self.ADMIN_IDS_RAW)
        fallback = os.getenv("ADMIN_IDS", self.ADMIN_IDS)
        parsed = _parse_ids(primary)
        if parsed:
            return parsed
        return _parse_ids(fallback)


settings = Settings()
