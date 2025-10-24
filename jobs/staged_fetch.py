from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx

log = logging.getLogger("bot")

try:  # pragma: no cover - optional dependency
    from curl_cffi import requests as curl_requests  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    curl_requests = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from playwright.async_api import async_playwright  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    async_playwright = None  # type: ignore[assignment]

_HAS_CURL_CFFI = curl_requests is not None
_HAS_PLAYWRIGHT = async_playwright is not None

try:  # pragma: no cover - optional dependency
    from playwright._impl._driver import compute_driver_executable  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    compute_driver_executable = None  # type: ignore[assignment]

_CAPABILITIES_LOGGED = False

TAX_HOST = "www.tax.gov.ua"
TAX_BASE_URL = f"https://{TAX_HOST}"
_TAX_WARMUP_URL = f"{TAX_BASE_URL}/"

_TAX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.7,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Referer": TAX_BASE_URL,
}


@dataclass(slots=True)
class _FetchPlan:
    url: str
    domain: str
    headers: dict[str, str]
    warmup_url: Optional[str] = None


def _chromium_available() -> bool:
    if not _HAS_PLAYWRIGHT or compute_driver_executable is None:
        return False
    try:
        path = compute_driver_executable()
    except Exception:  # pragma: no cover - best effort check
        return False
    return bool(path and path.exists())


def _log_capabilities_once() -> None:
    global _CAPABILITIES_LOGGED
    if _CAPABILITIES_LOGGED:
        return
    chromium_status = "YES" if _chromium_available() else "NO"
    log.info(
        "staged fetch capabilities: httpx http2=%s, curl_cffi=%s, playwright=%s (chromium=%s)",
        "ON",
        "OK" if _HAS_CURL_CFFI else "ABSENT",
        "OK" if _HAS_PLAYWRIGHT else "ABSENT",
        chromium_status,
    )
    _CAPABILITIES_LOGGED = True


def _normalize_tax_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{TAX_BASE_URL}{path}{query}"


def _build_plan(url: str) -> _FetchPlan:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.endswith("tax.gov.ua"):
        normalized = _normalize_tax_url(url)
        return _FetchPlan(url=normalized, domain=TAX_HOST, headers=dict(_TAX_HEADERS), warmup_url=_TAX_WARMUP_URL)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    }
    normalized = urlunparse(parsed)
    return _FetchPlan(url=normalized, domain=domain or normalized, headers=headers)


async def _httpx_fetch(plan: _FetchPlan, http2: bool) -> tuple[Optional[str], Optional[int]]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(
        headers=plan.headers,
        timeout=timeout,
        follow_redirects=True,
        http2=http2,
    ) as client:
        if plan.warmup_url:
            try:
                await client.get(plan.warmup_url)
            except Exception:  # pragma: no cover - best effort warmup
                pass
        response = await client.get(plan.url)
        if response.status_code == 200 and response.text:
            return response.text, response.status_code
        return None, response.status_code


async def _curl_cffi_fetch(plan: _FetchPlan) -> tuple[Optional[str], Optional[int]]:
    if not _HAS_CURL_CFFI:
        log.info("%s fetch step=curl_cffi skipped (module not installed)", plan.domain)
        return None, None

    def _run() -> tuple[Optional[str], Optional[int]]:
        try:
            response = curl_requests.get(  # type: ignore[operator]
                plan.url,
                headers=plan.headers,
                impersonate="chrome120",
                timeout=20,
                allow_redirects=True,
            )
        except Exception:
            return None, None
        if response.status_code == 200 and response.text:
            return response.text, response.status_code
        return None, response.status_code

    return await asyncio.to_thread(_run)


async def _playwright_fetch(plan: _FetchPlan) -> tuple[Optional[str], Optional[int]]:
    if not _HAS_PLAYWRIGHT:
        log.info("%s fetch step=playwright skipped (module not installed)", plan.domain)
        return None, None

    try:
        async with async_playwright() as p:  # type: ignore[misc]
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=plan.headers.get("User-Agent"))
            if plan.warmup_url:
                page = await context.new_page()
                try:
                    await page.goto(plan.warmup_url, wait_until="networkidle", timeout=20000)
                except Exception:
                    pass
                await page.close()
            page = await context.new_page()
            try:
                response = await page.goto(plan.url, wait_until="networkidle", timeout=30000)
                status = response.status if response is not None else None
                content = await page.content()
            finally:
                await context.close()
                await browser.close()
    except Exception:
        return None, None
    return content, status


async def staged_fetch_html(url: str) -> Optional[str]:
    """Fetch HTML using staged fallbacks for strict domains."""
    _log_capabilities_once()
    plan = _build_plan(url)

    steps = (
        ("httpx h2", lambda: _httpx_fetch(plan, http2=True)),
        ("httpx h1", lambda: _httpx_fetch(plan, http2=False)),
        ("curl_cffi", lambda: _curl_cffi_fetch(plan)),
        ("playwright", lambda: _playwright_fetch(plan)),
    )

    for label, factory in steps:
        try:
            html, status = await factory()
        except Exception:
            html, status = None, None
        if status is not None:
            log.info("%s fetch step=%s → status=%s", plan.domain, label, status)
        elif html is None:
            log.info("%s fetch step=%s → skipped", plan.domain, label)
        if html:
            return html
    log.warning("%s fetch failed after staged retries", plan.domain)
    return None


__all__ = ["staged_fetch_html"]
