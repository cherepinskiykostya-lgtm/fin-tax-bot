from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str
    BASE_URL: str | None = None
    DATABASE_URL: str | None = None
    CRON_TZ: str = "Europe/Bucharest"

    # ВАЖНО: сырая строка из переменной окружения, например "279895144,987654321"
    ADMIN_IDS_RAW: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # никаких специальных настроек не нужно: мы сами распарсим строку
    )

    # Вычисляемое свойство: получаем список int из строки ADMIN_IDS_RAW
    @property
    def ADMIN_IDS(self) -> list[int]:
        raw = (self.ADMIN_IDS_RAW or "").strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(",")]
        ids: list[int] = []
        for p in parts:
            if not p:
                continue
            # поддержим и пробелы, и случайные кавычки
            p = p.strip().strip('"').strip("'")
            ids.append(int(p))
        return ids


settings = Settings()
