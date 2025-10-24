from __future__ import annotations

import importlib
import importlib.util
import logging
from typing import Optional, Set

import httpx

log = logging.getLogger("bot")

REQUEST_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

HTTP2_SUPPORTED = importlib.util.find_spec("h2") is not None
CURL_CFFI_AVAILABLE = importlib.util.find_spec("curl_cffi") is not None
try:
    PLAYWRIGHT_AVAILABLE = importlib.util.find_spec("playwright.async_api") is not None
except ModuleNotFoundError:
    PLAYWRIGHT_AVAILABLE = False

_curl_cffi_requests = importlib.import_module("curl_cffi.requests") if CURL_CFFI_AVAILABLE else None
if PLAYWRIGHT_AVAILABLE:
    try:
        _playwright_async_api = importlib.import_module("playwright.async_api")
    except ModuleNotFoundError:
        _playwright_async_api = None
        PLAYWRIGHT_AVAILABLE = False
else:
    _playwright_async_api = None

_CAPABILITIES_LOGGED = False


def _to_www(url: str) -> str:
    if "://tax.gov.ua" in url and "://www.tax.gov.ua" not in url:
        return url.replace("://tax.gov.ua", "://www.tax.gov.ua")
    return url


def _log_capabilities_once() -> None:
    global _CAPABILITIES_LOGGED
    if _CAPABILITIES_LOGGED:
        return
    log.info("tax.gov.ua capability http2: %s", "ON" if HTTP2_SUPPORTED else "OFF")
    log.info("tax.gov.ua capability curl_cffi: %s", "OK" if CURL_CFFI_AVAILABLE else "ABSENT")
    log.info("tax.gov.ua capability playwright: %s", "OK" if PLAYWRIGHT_AVAILABLE else "ABSENT")
    _CAPABILITIES_LOGGED = True


def _log_skip(step: str, reason: str) -> None:
    log.info("tax.gov.ua fetch step=%s skipped (%s)", step, reason)


async def _try_httpx(url: str, referer: str, http2: bool) -> Optional[str]:
    headers = {**REQUEST_HEADERS_BROWSER, "Referer": referer}
    headers["Accept-Encoding"] = "gzip, deflate, br" if http2 else "gzip, deflate"
    label = "h2" if http2 else "h1"
    try:
        log.info("tax.gov.ua fetch step=httpx %s starting url=%s", label, url)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers=headers,
            http2=http2,
        ) as client:
            try:
                await client.get(referer)
            except Exception as warmup_exc:
                log.debug("tax.gov.ua warmup (%s) error: %s", label, warmup_exc)
            response = await client.get(url, headers=headers)
        if response.status_code == 200 and response.text:
            log.info("tax.gov.ua fetch step=httpx %s status=%s -> success", label, response.status_code)
            return response.text
        log.info("tax.gov.ua fetch step=httpx %s status=%s -> retry", label, response.status_code)
    except Exception as exc:
        log.info("tax.gov.ua fetch step=httpx %s error=%s -> retry", label, exc)
    return None


async def fetch_taxgov_html(url: str, failed_sources: Set[str] | None = None) -> Optional[str]:
    """Attempt to fetch tax.gov.ua content with progressively stronger clients."""

    _log_capabilities_once()

    target_url = _to_www(url)
    referer = "https://www.tax.gov.ua/"

    if HTTP2_SUPPORTED:
        html = await _try_httpx(target_url, referer, http2=True)
        if html:
            return html
    else:
        _log_skip("httpx h2", "http2 not available")

    html = await _try_httpx(target_url, referer, http2=False)
    if html:
        return html

    if CURL_CFFI_AVAILABLE and _curl_cffi_requests is not None:
        session = None
        try:
            log.info("tax.gov.ua fetch step=curl_cffi starting url=%s", target_url)
            session = _curl_cffi_requests.Session()
            session.headers.update(REQUEST_HEADERS_BROWSER)
            session.impersonate = "chrome124"
            try:
                session.get(referer, timeout=25)
            except Exception as warmup_exc:
                log.debug("tax.gov.ua curl_cffi warmup error: %s", warmup_exc)
            response = session.get(target_url, timeout=25)
            if response.status_code == 200 and response.text:
                log.info("tax.gov.ua fetch step=curl_cffi status=%s -> success", response.status_code)
                return response.text
            log.info("tax.gov.ua fetch step=curl_cffi status=%s -> retry", response.status_code)
        except Exception as exc:
            log.info("tax.gov.ua fetch step=curl_cffi error=%s -> retry", exc)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
    else:
        _log_skip("curl_cffi", "module not installed")

    if PLAYWRIGHT_AVAILABLE and _playwright_async_api is not None:
        browser = None
        context = None
        try:
            log.info("tax.gov.ua fetch step=playwright starting url=%s", target_url)
            async with _playwright_async_api.async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
                context = await browser.new_context(
                    user_agent=REQUEST_HEADERS_BROWSER["User-Agent"],
                    locale="uk-UA",
                    extra_http_headers=REQUEST_HEADERS_BROWSER,
                )
                page = await context.new_page()
                try:
                    await page.goto(referer, wait_until="domcontentloaded", timeout=25000)
                except Exception as warmup_exc:
                    log.debug("tax.gov.ua playwright warmup error: %s", warmup_exc)
                response = await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                status = getattr(response, "status", None)
                if status == 200:
                    html = await page.content()
                    log.info("tax.gov.ua fetch step=playwright status=%s -> success", status)
                    return html
                log.info("tax.gov.ua fetch step=playwright status=%s -> retry", status)
        except Exception as exc:
            log.info("tax.gov.ua fetch step=playwright error=%s -> retry", exc)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
    else:
        _log_skip("playwright", "module not installed")

    if failed_sources is not None:
        failed_sources.add("www.tax.gov.ua")
    log.warning("tax.gov.ua fetch failed after all steps url=%s", target_url)
    return None


__all__ = [
    "HTTP2_SUPPORTED",
    "REQUEST_HEADERS_BROWSER",
    "fetch_taxgov_html",
]
