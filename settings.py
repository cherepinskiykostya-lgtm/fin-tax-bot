from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str
    BASE_URL: str | None = None
    DATABASE_URL: str | None = None
    CRON_TZ: str = "Europe/Bucharest"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
