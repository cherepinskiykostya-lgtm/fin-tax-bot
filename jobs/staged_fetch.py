from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from importlib import util as importlib_util
from pathlib import Path
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


@dataclass(slots=True)
class _StepResult:
    html: Optional[str]
    status: Optional[int]
    executed: bool
    error: Optional[str] = None

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
    if not _HAS_PLAYWRIGHT:
        return False

    if compute_driver_executable is not None:
        try:
            path_obj = compute_driver_executable()
        except Exception:  # pragma: no cover - best effort check
            path_obj = None
        if path_obj:
            if isinstance(path_obj, tuple):
                path_obj = path_obj[0]
            try:
                candidate = Path(path_obj)
            except TypeError:  # pragma: no cover - defensive
                candidate = None
            if candidate is not None:
                return candidate.exists()

    return False


def _http2_available() -> bool:
    try:
        return importlib_util.find_spec("h2") is not None
    except Exception:  # pragma: no cover - best effort check
        return False


def _log_capabilities_once() -> None:
    global _CAPABILITIES_LOGGED
    if _CAPABILITIES_LOGGED:
        return
    try:
        chromium_status = "YES" if _chromium_available() else "NO"
    except Exception as exc:  # pragma: no cover - defensive logging guard
        log.info("staged fetch capabilities: chromium check failed: %s", exc)
        chromium_status = "NO"
    http2_status = "ON" if _http2_available() else "OFF"
    log.info(
        "staged fetch capabilities: httpx http2=%s, curl_cffi=%s, playwright=%s (chromium=%s)",
        http2_status,
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


async def _httpx_fetch(plan: _FetchPlan, http2: bool) -> _StepResult:
    timeout = httpx.Timeout(20.0)
    try:
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
    except Exception as exc:  # pragma: no cover - network flake handling
        return _StepResult(html=None, status=None, executed=True, error=str(exc))

    status = response.status_code
    if status == 200 and response.text:
        return _StepResult(html=response.text, status=status, executed=True)
    return _StepResult(html=None, status=status, executed=True)


async def _curl_cffi_fetch(plan: _FetchPlan) -> _StepResult:
    if not _HAS_CURL_CFFI:
        return _StepResult(html=None, status=None, executed=False)

    def _run() -> _StepResult:
        session = None
        try:
            session = curl_requests.Session(  # type: ignore[operator]
                impersonate="chrome120",
                timeout=20,
            )
            if plan.warmup_url:
                try:
                    session.get(
                        plan.warmup_url,
                        headers=plan.headers,
                        allow_redirects=True,
                    )
                except Exception:
                    pass
            response = session.get(
                plan.url,
                headers=plan.headers,
                allow_redirects=True,
            )
            status = response.status_code
            if status == 200 and response.text:
                return _StepResult(html=response.text, status=status, executed=True)
            return _StepResult(html=None, status=status, executed=True)
        except Exception as exc:  # pragma: no cover - curl runtime issues
            return _StepResult(html=None, status=None, executed=True, error=str(exc))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    return await asyncio.to_thread(_run)


async def _playwright_fetch(plan: _FetchPlan) -> _StepResult:
    if not _HAS_PLAYWRIGHT:
        return _StepResult(html=None, status=None, executed=False)

    try:
        async with async_playwright() as p:  # type: ignore[misc]
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=plan.headers.get("User-Agent"),
                extra_http_headers={k: v for k, v in plan.headers.items() if v},
            )
            if plan.warmup_url:
                page = await context.new_page()
                try:
                    await page.goto(plan.warmup_url, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
                await page.close()
            page = await context.new_page()
            try:
                response = await page.goto(
                    plan.url,
                    wait_until="networkidle",
                    timeout=30000,
                    referer=plan.headers.get("Referer"),
                )
                await page.wait_for_timeout(2000)
                status = response.status if response is not None else None
                content = await page.content()
            finally:
                await context.close()
                await browser.close()
    except Exception as exc:  # pragma: no cover - playwright runtime issues
        return _StepResult(html=None, status=None, executed=True, error=str(exc))
    return _StepResult(html=content, status=status, executed=True)


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
            result = await factory()
        except Exception as exc:  # pragma: no cover - unexpected wrapper failure
            log.info("%s fetch step=%s → error=%s", plan.domain, label, exc)
            continue

        if not result.executed:
            log.info("%s fetch step=%s → skipped", plan.domain, label)
            continue

        if result.status is not None:
            log.info("%s fetch step=%s → status=%s", plan.domain, label, result.status)
        elif result.error:
            log.info("%s fetch step=%s → error=%s", plan.domain, label, result.error)
        else:
            log.info("%s fetch step=%s → completed", plan.domain, label)

        if result.html:
            return result.html
    log.warning("%s fetch failed after staged retries", plan.domain)
    return None


__all__ = ["staged_fetch_html"]
