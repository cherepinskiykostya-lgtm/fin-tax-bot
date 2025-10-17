import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode

import httpx
import feedparser
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from settings import settings
from db.session import SessionLocal
from db.models import Article

log = logging.getLogger("bot")

TOPIC_QUERIES = {
    "PillarTwo": '("Pillar Two" OR GloBE OR BEPS) site:oecd.org OR site:europa.eu OR site:eur-lex.europa.eu',
    "CFC": '(КІК OR "controlled foreign company" OR CFC) site:zakon.rada.gov.ua OR site:tax.gov.ua OR site:minfin.gov.ua',
    "CRS": '(AEOI OR CRS OR FATCA) site:oecd.org OR site:nabu.gov.ua OR site:bank.gov.ua',
    "BO": '(UBO OR "beneficial owner" OR бенефіціар) site:minjust.gov.ua OR site:europa.eu',
    "TP": '("transfer pricing" OR ТЦУ) site:tax.gov.ua OR site:zakon.rada.gov.ua',
    "WHT": '("withholding tax" OR WHT) site:europa.eu OR site:oecd.org',
    "IPBox": '("IP Box" OR R&D) site:europa.eu OR site:oecd.org',
    "HOLDING": '(KYC OR сабстенс OR substance) site:europa.eu OR site:oecd.org OR site:bank.gov.ua',
    "UA_TAX": '(податкові зміни OR законопроект) site:zakon.rada.gov.ua OR site:minfin.gov.ua OR site:tax.gov.ua',
    "NBU": '(НБУ OR "National Bank of Ukraine") site:bank.gov.ua',
    "DiiaCity": '("Дія Сіті" OR Diia City) site:diia.gov.ua OR site:tax.gov.ua OR site:zakon.rada.gov.ua',
    "CASELAW": '("Court of Justice" OR судова практика) site:curia.europa.eu OR site:reyestr.court.gov.ua',
    "PRACTICE": '("tax alert" OR "tax newsletter") site:kpmg.com OR site:ey.com OR site:pwc.com OR site:deloitte.com OR site:taxfoundation.org',
}

SEED_RSS = [
    "https://www.oecd.org/tax/topics/tax-challenges-arising-from-the-digitalisation-of-the-economy/feed/",
    "https://eur-lex.europa.eu/homepage.html?locale=en&WT.rss_f=EUR-Lex%20-%20News&WT.rss_a=All%20content&WT.rss_ev=a&WT.rss_fv=1&WT.rss_s=1&type=rss",
    "https://bank.gov.ua/control/uk/publish/rss?cat_id=258190",  # НБУ новини
    "https://tax.gov.ua/rss/",  # ДПС
    # при необходимости добавим ещё
]

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _in_whitelist_lvl1(domain: str) -> bool:
    return any(domain.endswith(d.strip()) for d in settings.whitelist_level1)

async def _fetch_html(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and r.text:
                return r.text
    except Exception:
        return None
    return None

def _extract_image(html: str) -> str | None:
    try:
        tree = HTMLParser(html)
        # og:image
        og = tree.css_first('meta[property="og:image"]')
        if og and og.attributes.get("content"):
            return og.attributes["content"]
        tw = tree.css_first('meta[name="twitter:image"]')
        if tw and tw.attributes.get("content"):
            return tw.attributes["content"]
    except Exception:
        return None
    return None

async def ingest_one(url: str, title: str, published: datetime | None, summary: str | None):
    dom = _domain(url)
    lvl1 = _in_whitelist_lvl1(dom)

    # простая проверка дубликатов
    async with SessionLocal() as s:
        exists = (await s.execute(select(Article.id).where(Article.url == url))).scalar_one_or_none()
        if exists:
            return

        image_url = None
        html = await _fetch_html(url)
        if html:
            image_url = _extract_image(html)

        art = Article(
            title=title or url,
            url=url,
            source_domain=dom,
            published_at=published,
            summary=summary,
            image_url=image_url,
            level1_ok=lvl1,
            topics=None,
        )
        s.add(art)
        await s.commit()

async def run_ingest_cycle():
    # 1) RSS seed
    for feed_url in SEED_RSS:
        try:
            fp = feedparser.parse(feed_url)
            for e in fp.entries[:20]:
                link = getattr(e, "link", None)
                title = getattr(e, "title", "")
                summary = getattr(e, "summary", None)
                published = None
                if getattr(e, "published_parsed", None):
                    published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                if link:
                    await ingest_one(link, title, published, summary)
        except Exception as e:
            log.warning("RSS error %s: %s", feed_url, e)

    # 2) Google News
    if settings.ENABLE_GOOGLE_NEWS:
        base = "https://news.google.com/rss/search?"
        for topic, q in TOPIC_QUERIES.items():
            params = {"q": q, "hl": "uk", "gl": "UA", "ceid": "UA:uk"}
            url = base + urlencode(params)
            try:
                fp = feedparser.parse(url)
                for e in fp.entries[:20]:
                    link = getattr(e, "link", None)
                    title = getattr(e, "title", "")
                    summary = getattr(e, "summary", None)
                    published = None
                    if getattr(e, "published_parsed", None):
                        published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                    if link:
                        await ingest_one(link, title, published, summary)
            except Exception as e:
                log.warning("GNews error %s: %s", topic, e)
