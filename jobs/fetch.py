import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from settings import settings
from db.session import SessionLocal
from db.models import Article
from jobs.nbu_scraper import fetch_nbu_news, NBU_NEWS_URL
from jobs.tax_scraper import fetch_tax_news, TAX_NEWS_URL
from jobs.staged_fetch import staged_fetch_html
from services.tax_urls import tax_print_url
from services.summary import choose_summary, normalize_text
from services.nbu_article import (
    extract_body_fallback_generic,
    extract_nbu_body,
    is_reliable_nbu_body,
)
from services.image_extract import extract_image

log = logging.getLogger("bot")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

REQUEST_HEADERS_HTML = {
    "User-Agent": REQUEST_HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": REQUEST_HEADERS.get("Accept-Language", "uk-UA,uk;q=0.9,en;q=0.8"),
}

async def _fetch_tax_article_htmls(
    url: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    primary_html: Optional[str] = None
    print_html: Optional[str] = None
    print_url: Optional[str] = None

    try:
        primary_html = await staged_fetch_html(url)
    except Exception as exc:  # pragma: no cover - network/runtime guard
        log.warning("tax html fetch exception %s: %s", url, exc)
        primary_html = None

    print_url = tax_print_url(url)
    if print_url:
        if print_url == url:
            print_html = primary_html
        else:
            try:
                print_html = await staged_fetch_html(print_url)
                if print_html:
                    log.debug("tax print html fetched %s", print_url)
            except Exception as exc:  # pragma: no cover - network/runtime guard
                log.info("tax print fetch exception %s: %s", print_url, exc)
                print_html = None
    else:
        log.debug("tax print url not derived for %s", url)

    return primary_html, print_html, print_url

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

def _normalize_url(url: str) -> str:
    """Unwrap helper redirects (e.g. Google News) to the original article URL."""
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    host = parsed.netloc.lower()
    if host.endswith("news.google.com"):
        params = parse_qs(parsed.query)
        for key in ("url", "u"):
            target = params.get(key)
            if target and target[0]:
                return target[0]
    print_url = tax_print_url(url)
    if print_url:
        return print_url
    return url


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _resource_key_label(source: str, default_label: str | None = None) -> tuple[str, str]:
    """Normalize resource identifiers for reporting."""
    if default_label is not None:
        return source, default_label
    try:
        parsed = urlparse(source)
        host = parsed.netloc.lower()
        if host:
            return host, host
    except Exception:
        pass
    label = default_label or source
    return source, label

def _in_whitelist_lvl1(domain: str) -> bool:
    return any(domain.endswith(d.strip()) for d in settings.whitelist_level1)

async def _fetch_html(
    url: str,
    failed_sources: set[str] | None = None,
    headers: dict[str, str] | None = None,
) -> str | None:
    domain = ""
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        domain = ""

    if domain.endswith("tax.gov.ua"):
        try:
            log.debug("staged fetch html: %s", url)
            html = await staged_fetch_html(url)
        except Exception as exc:
            log.warning("staged html fetch exception %s: %s", url, exc)
            html = None
        if html:
            return html
        log.warning("html fetch failed %s: staged fetch returned no content", url)
        if failed_sources is not None:
            failed_sources.add(domain or url)
        return None

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20,
            headers=headers or REQUEST_HEADERS_HTML,
        ) as client:
            log.debug("fetching html: %s", url)
            r = await client.get(url)
            if r.status_code == 200 and r.text:
                return r.text
            log.warning("html fetch failed %s: status=%s", url, r.status_code)
            if failed_sources is not None:
                failed_sources.add(_domain(url) or url)
    except Exception as exc:
        log.warning("html fetch exception %s: %s", url, exc)
        if failed_sources is not None:
            failed_sources.add(_domain(url) or url)
        return None
    return None


async def _load_feed(
    client: httpx.AsyncClient,
    url: str,
    failed_sources: set[str] | None = None,
) -> Optional[feedparser.FeedParserDict]:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        log.warning("Feed fetch error %s: %s", url, exc)
        if failed_sources is not None:
            key, _ = _resource_key_label(url)
            failed_sources.add(key)
        return None

    if response.status_code != httpx.codes.OK:
        log.warning("Feed fetch failed %s: HTTP %s", url, response.status_code)
        if failed_sources is not None:
            key, _ = _resource_key_label(url)
            failed_sources.add(key)
        return None

    final_host = response.url.host or ""
    if "consent.google.com" in final_host:
        log.warning("Google News feed requires consent, skipping: %s", url)
        if failed_sources is not None:
            key, _ = _resource_key_label(url)
            failed_sources.add(key)
        return None

    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None):
        log.warning("Feed parsing issue %s: %s", url, parsed.bozo_exception)
    return parsed

async def ingest_one(
    url: str,
    title: str,
    published: datetime | None,
    summary: str | None,
    failed_sources: set[str] | None = None,
) -> str:
    normalized_url = _normalize_url(url)
    dom = _domain(normalized_url)
    lvl1 = _in_whitelist_lvl1(dom)

    if not lvl1:
        log.info(
            "skip article not in level1 whitelist domain=%s url=%s original=%s",
            dom,
            normalized_url,
            url,
        )
        return "skipped_level1"

    try:
        async with SessionLocal() as s:
            candidates = tuple({normalized_url, url})
            exists = (
                await s.execute(
                    select(Article.id).where(Article.url.in_(candidates))
                )
            ).scalar_one_or_none()
            if exists:
                log.info("skip duplicate article url=%s existing_id=%s", url, exists)
                return "duplicate"

            image_url = None

            html: Optional[str]
            html_for_summary: Optional[str]
            image_source_html: Optional[str]

            summary_source_url = normalized_url
            summary_source_kind = "primary"
            derived_print_url: Optional[str] = None

            if dom.endswith("tax.gov.ua"):
                primary_html, print_html, print_url = await _fetch_tax_article_htmls(normalized_url)
                derived_print_url = print_url
                html = primary_html or print_html
                html_for_summary = print_html or primary_html
                image_source_html = primary_html or print_html
                if html_for_summary and html_for_summary is print_html and print_url:
                    summary_source_url = print_url
                    summary_source_kind = "print"
                elif html_for_summary:
                    summary_source_kind = "primary"
                if not html:
                    log.debug("no html content for %s", normalized_url)
                    if failed_sources is not None:
                        failed_sources.add(dom or normalized_url)
            else:
                html = await _fetch_html(normalized_url, failed_sources=failed_sources)
                html_for_summary = html
                image_source_html = html
                if html_for_summary:
                    summary_source_kind = "primary"

            parser_source_url: Optional[str] = None
            if html_for_summary:
                parser_source_url = summary_source_url
            elif html:
                parser_source_url = normalized_url

            if parser_source_url:
                log.info(
                    "article parser input url=%s source_kind=%s parser_source_url=%s",
                    normalized_url,
                    summary_source_kind,
                    parser_source_url,
                )

            summary_candidate = summary

            if image_source_html:
                image_url = extract_image(
                    image_source_html,
                    base_url=parser_source_url or normalized_url or url,
                )

            if dom.endswith("bank.gov.ua"):
                if not html:
                    log.warning(
                        "skip NBU article: html fetch failed url=%s",
                        normalized_url,
                    )
                    return "skipped_no_body"
                body_text = extract_nbu_body(html)
                if not body_text:
                    body_text = extract_body_fallback_generic(html)
                if body_text:
                    summary_candidate = body_text
                else:
                    log.warning(
                        "NBU: both primary and fallback body extract failed url=%s",
                        normalized_url,
                    )
                    return "skipped_no_body"
            else:
                if html_for_summary:
                    summary_candidate = choose_summary(title or "", summary_candidate, html_for_summary)
                elif not html:
                    log.debug("no html content for %s", normalized_url)
                    if failed_sources is not None:
                        failed_sources.add(dom or normalized_url)

            summary_text = normalize_text(summary_candidate)

            log.info(
                "article body extracted url=%s source_kind=%s source_url=%s print_url=%s text=%s",
                normalized_url,
                summary_source_kind,
                summary_source_url,
                derived_print_url,
                summary_text,
            )

            if dom.endswith("bank.gov.ua"):
                if not is_reliable_nbu_body(summary_text, html):
                    log.warning(
                        "skip NBU article: body not reliably extracted url=%s",
                        normalized_url,
                    )
                    return "skipped_no_body"

            if not summary_text:
                log.warning(
                    "skip article without extracted body url=%s source_kind=%s source_url=%s print_url=%s title=%s",
                    normalized_url,
                    summary_source_kind,
                    summary_source_url,
                    derived_print_url,
                    title,
                )
                return "skipped_no_body"
            art = Article(
                title=title or normalized_url,
                url=normalized_url,
                source_domain=dom,
                published_at=published,
                summary=summary_text,
                image_url=image_url,
                level1_ok=lvl1,
                topics=None,
            )
            s.add(art)
            await s.commit()
            await s.refresh(art)
            log.info(
                "stored article id=%s domain=%s level1=%s published=%s",
                art.id,
                dom,
                lvl1,
                published,
            )
            return "created"
    except Exception:
        log.exception("failed to ingest article url=%s", url)
        return "error"

def _entry_published(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                return None
    return None


async def run_ingest_cycle():
    log.info("starting ingest cycle")
    results: Counter[str] = Counter()
    failed_sources: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    resource_details: dict[str, dict[str, int | str | bool]] = {}

    def ensure_resource(key: str, label: str) -> dict[str, int | str | bool]:
        return resource_details.setdefault(
            key,
            {
                "name": label,
                "available": True,
                "created": 0,
            },
        )

    # 1) RSS seed
    for feed_url in SEED_RSS:
        key, label = _resource_key_label(feed_url)
        resource_info = ensure_resource(key, label)
        try:
            log.info("processing seed feed %s", feed_url)
            fp = feedparser.parse(feed_url)
            for e in fp.entries[:20]:
                link = getattr(e, "link", None)
                title = getattr(e, "title", "")
                summary = getattr(e, "summary", None)
                published = _entry_published(e)
                if not published:
                    results["skipped_no_date"] += 1
                    continue
                if published < cutoff:
                    results["skipped_old"] += 1
                    continue
                if link:
                    status = await ingest_one(link, title, published, summary, failed_sources=failed_sources)
                    results[status] += 1
                    if status == "created":
                        resource_info["created"] = int(resource_info["created"]) + 1
                else:
                    log.debug("entry without link in feed %s", feed_url)
        except Exception as e:
            log.warning("RSS error %s: %s", feed_url, e)
            failed_sources.add(key)
            resource_info["available"] = False

    # 2) NBU HTML news source
    key, label = _resource_key_label("nbu:html", default_label="NBU News (HTML)")
    resource_info = ensure_resource(key, label)
    try:
        log.info("processing NBU news page %s", NBU_NEWS_URL)
        nbu_items = await fetch_nbu_news()
        if not nbu_items:
            resource_info["available"] = False
        for item in nbu_items:
            published = getattr(item, "published", None)
            if not published:
                results["skipped_no_date"] += 1
                continue
            if published < cutoff:
                results["skipped_old"] += 1
                continue
            status = await ingest_one(
                item.url,
                getattr(item, "title", ""),
                published,
                getattr(item, "summary", None),
                failed_sources=failed_sources,
            )
            results[status] += 1
            if status == "created":
                resource_info["created"] = int(resource_info["created"]) + 1
    except Exception:
        log.exception("NBU scraper error")
        resource_info["available"] = False
        failed_sources.add("bank.gov.ua")

    # 3) DPS HTML news source
    key, label = _resource_key_label("tax:html", default_label="DPS News (HTML)")
    resource_info = ensure_resource(key, label)
    try:
        log.info("processing DPS news page %s", TAX_NEWS_URL)
        tax_items = await fetch_tax_news()
        if not tax_items:
            resource_info["available"] = False
        for item in tax_items:
            published = getattr(item, "published", None)
            if not published:
                results["skipped_no_date"] += 1
                continue
            if published < cutoff:
                results["skipped_old"] += 1
                continue
            status = await ingest_one(
                item.url,
                getattr(item, "title", ""),
                published,
                getattr(item, "summary", None),
                failed_sources=failed_sources,
            )
            results[status] += 1
            if status == "created":
                resource_info["created"] = int(resource_info["created"]) + 1
    except Exception:
        log.exception("DPS scraper error")
        resource_info["available"] = False
        failed_sources.add("tax.gov.ua")

    # 4) Google News
    if settings.ENABLE_GOOGLE_NEWS:
        base = "https://news.google.com/rss/search?"
        async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=REQUEST_HEADERS) as client:
            for topic, q in TOPIC_QUERIES.items():
                params = {"q": q, "hl": "uk", "gl": "UA", "ceid": "UA:uk"}
                url = base + urlencode(params)
                key, label = _resource_key_label(f"google:{topic}", default_label=f"Google News ({topic})")
                resource_info = ensure_resource(key, label)
                fp = await _load_feed(client, url, failed_sources=failed_sources)
                if not fp:
                    resource_info["available"] = False
                    continue
                for e in fp.entries[:20]:
                    link = getattr(e, "link", None)
                    title = getattr(e, "title", "")
                    summary = getattr(e, "summary", None)
                    published = _entry_published(e)
                    if not published:
                        results["skipped_no_date"] += 1
                        continue
                    if published < cutoff:
                        results["skipped_old"] += 1
                        continue
                    if link:
                        status = await ingest_one(link, title, published, summary, failed_sources=failed_sources)
                        results[status] += 1
                        if status == "created":
                            resource_info["created"] = int(resource_info["created"]) + 1
                    else:
                        log.debug("entry without link in topic %s", topic)
    if results:
        log.info(
            "ingest cycle finished: created=%s duplicate=%s skipped_level1=%s error=%s "
            "skipped_old=%s skipped_no_date=%s skipped_no_body=%s",
            results.get("created", 0),
            results.get("duplicate", 0),
            results.get("skipped_level1", 0),
            results.get("error", 0),
            results.get("skipped_old", 0),
            results.get("skipped_no_date", 0),
            results.get("skipped_no_body", 0),
        )
    else:
        log.info("ingest cycle finished: no entries processed")
    if failed_sources:
        log.warning("ingest cycle had unavailable sources: %s", ", ".join(sorted(failed_sources)))

    for src in sorted(failed_sources):
        key, label = _resource_key_label(src)
        info = ensure_resource(key, label)
        info["available"] = False

    resources_report = sorted(
        (
            {
                "name": str(info["name"]),
                "available": bool(info["available"]),
                "created": int(info["created"]),
            }
            for info in resource_details.values()
        ),
        key=lambda item: item["name"].lower(),
    )

    return {
        "results": results,
        "failed_sources": sorted(failed_sources),
        "resources": resources_report,
    }
