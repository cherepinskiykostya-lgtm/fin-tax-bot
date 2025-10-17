import os
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str
    BASE_URL: str | None = None
    DATABASE_URL: str | None = None
    CRON_TZ: str = "Europe/Bucharest"

    # Админы (через запятую). Можно задавать ADMIN_IDS_RAW или ADMIN_IDS.
    ADMIN_IDS_RAW: str = ""
    ADMIN_IDS: str = ""

    # Канал для публикаций (numeric id вида -100xxxxxxxxxx или @username)
    CHANNEL_ID: str

    # LLM (OpenAI совместимый)
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Google News поиск по темам (включить/выключить)
    ENABLE_GOOGLE_NEWS: bool = True

    # Бел-лист доменов (Рівень 1 и 2)
    WHITELIST_LEVEL1: str = (
        "oecd.org, europa.eu, eur-lex.europa.eu, zakon.rada.gov.ua, bank.gov.ua, diia.gov.ua, "
        "tax.gov.ua, minfin.gov.ua, minjust.gov.ua, reyestr.court.gov.ua, curia.europa.eu, "
        "irs.gov, gov.uk, hmrc.gov.uk, bundesfinanzministerium.de, agenziaentrate.gov.it, "
        "tax.gov.ae, cbu.ae, ec.europa.eu"
    )
    WHITELIST_LEVEL2: str = (
        "kpmg.com, ey.com, pwc.com, deloitte.com, bdo.global, grantthornton.global, "
        "mazars.com, bakertilly.global, taxfoundation.org"
    )

    # UTM для «Джерела»
    UTM_SOURCE: str = "tg_channel"
    UTM_MEDIUM: str = "post"
    UTM_CAMPAIGN: str = "tax_watch"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def admin_id_list(self) -> list[int]:
        raw = os.getenv("ADMIN_IDS_RAW", self.ADMIN_IDS_RAW) or os.getenv("ADMIN_IDS", self.ADMIN_IDS) or ""
        items = [x.strip().strip("'").strip('"') for x in raw.split(",") if x.strip()]
        out: list[int] = []
        for it in items:
            try:
                out.append(int(it))
            except Exception:
                pass
        return out

    @property
    def whitelist_level1(self) -> list[str]:
        return _parse_list(self.WHITELIST_LEVEL1)

    @property
    def whitelist_level2(self) -> list[str]:
        return _parse_list(self.WHITELIST_LEVEL2)


settings = Settings()
