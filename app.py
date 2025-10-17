from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str
    BASE_URL: str | None = None
    DATABASE_URL: str | None = None
    CRON_TZ: str = "Europe/Bucharest"

    # Список Telegram user_id, которым разрешено пользоваться ботом
    ADMIN_IDS: list[int] = []

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        """Парсим строку '1,2,3' в список int"""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            try:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except ValueError:
                raise ValueError("ADMIN_IDS must be a comma-separated list of integers")
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        return []

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
