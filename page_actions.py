"""
Page interaction helpers — cookie overlay, age gate, ad tab recovery,
link extraction, and BFS crawl.
Ported from qa-automation's lib/qa_page_actions.py.
"""

import re
import time
import asyncio
import logging
from urllib.parse import urljoin, urlparse, urldefrag
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

COOKIE_OVERLAY_SELECTOR = "#ch2-dialog"
COOKIE_OVERLAY_ACCEPT_SELECTOR = "button.ch2-allow-all-btn"

UTILITY_PATH_PREFIXES = [
    "/admin", "/wp-admin", "/wp-login.php", "/login", "/logout", "/xmlrpc.php",
]


def normalize_internal_url(raw_url: str, base_url: str) -> Optional[str]:
    if not raw_url or raw_url.startswith(("mailto:", "tel:", "javascript:")):
        return None
    base = urlparse(base_url)
    parsed = urlparse(urljoin(base_url, raw_url))
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() != base.netloc.lower():
        return None
    path = parsed.path.lower()
    if (
        path.startswith("/wp-admin")
        or path.startswith("/wp-login.php")
        or path.startswith("/xmlrpc.php")
        or "/feed/" in path
        or path.endswith("/feed")
    ):
        return None
    clean_url, _ = urldefrag(parsed.geturl())
    return clean_url.rstrip("/") if parsed.path != "/" else clean_url


def classify_page_url(raw_url: str, expected_origin: str) -> str:
    try:
        parsed = urlparse(raw_url)
        expected = urlparse(expected_origin)
    except Exception:
        return "unknown"
    if not parsed.scheme or not parsed.netloc:
        return "unknown"
    return "site" if parsed.scheme == expected.scheme and parsed.netloc == expected.netloc else "ad"


def is_likely_blocked(text: str, title: str = "") -> bool:
    import re
    combined = f"{title}\n{text}".lower()
    return bool(
        re.search(
            r"captcha|challenge|unusual traffic|verify you are human|"
            r"checking your browser|access denied|temporarily blocked|"
            r"too many requests|rate limit|cloudflare",
            combined,
        )
    )


async def recover_cookie_or_ad_tabs(page, expected_origin: str, safe_return_url: Optional[str] = None):
    context = page.context
    pages = list(context.pages)
    active_page = page

    if classify_page_url(page.url, expected_origin) != "site":
        for candidate in pages:
            if classify_page_url(candidate.url, expected_origin) == "site":
                active_page = candidate
                break

    for candidate in pages:
        if candidate == active_page:
            continue
        if classify_page_url(candidate.url, expected_origin) == "ad":
            log.info("Closing ad/off-origin tab: %s", candidate.url)
            try:
                await candidate.close()
            except Exception:
                pass

    if classify_page_url(active_page.url, expected_origin) != "site" and safe_return_url:
        before_url = active_page.url
        try:
            await active_page.goto(safe_return_url, wait_until="domcontentloaded", timeout=30000)
            log.info("Returned to site after ad page: %s -> %s", before_url, active_page.url)
        except Exception:
            pass

    return active_page


async def accept_cookie_overlay_if_visible(page, expected_origin: str, safe_return_url: Optional[str] = None):
    dialog = page.locator(COOKIE_OVERLAY_SELECTOR).first
    try:
        visible = await dialog.is_visible(timeout=1500)
    except Exception:
        visible = False

    log.info("Cookie overlay check: selector=%s visible=%s page=%s", COOKIE_OVERLAY_SELECTOR, visible, page.url)
    if not visible:
        return page

    button = page.locator(COOKIE_OVERLAY_ACCEPT_SELECTOR).first
    popup_task = asyncio.create_task(page.context.wait_for_event("page", timeout=5000))
    try:
        await button.click(timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
    except Exception as exc:
        log.info("Cookie overlay accept click failed: %s", exc)
    try:
        new_page = await popup_task
        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
        log.info("Cookie overlay click opened tab: %s", new_page.url)
    except Exception:
        pass

    return await recover_cookie_or_ad_tabs(page, expected_origin, safe_return_url)


async def acknowledge_age_gate_if_present(page, expected_origin: Optional[str] = None,
                                           safe_return_url: Optional[str] = None,
                                           simulate_fn=None):
    if expected_origin:
        page = await accept_cookie_overlay_if_visible(page, expected_origin, safe_return_url)

    candidates = [
        page.locator("text=/I am 18|18 or older|Enter site|I agree|Continue/i").first,
        page.get_by_role("button", name=re.compile(r"18|enter|agree|accept|continue", re.I)).first,
        page.get_by_role("link", name=re.compile(r"18|enter|agree|accept|continue", re.I)).first,
    ]

    for candidate in candidates:
        try:
            if await candidate.count() > 0 and await candidate.is_visible():
                if simulate_fn:
                    await simulate_fn(page)
                await candidate.click()
                await page.wait_for_load_state("domcontentloaded")
                if expected_origin:
                    page = await recover_cookie_or_ad_tabs(page, expected_origin, safe_return_url)
                return page
        except Exception:
            continue
    return page


async def extract_internal_links(page, base_url: str) -> List[str]:
    hrefs = await page.locator("a[href]").evaluate_all("anchors => anchors.map(a => a.href)")
    links = {
        normalized
        for href in hrefs
        if (normalized := normalize_internal_url(href, base_url))
    }
    return sorted(links)


async def crawl_links_breadth_first(page, start_url: str, max_depth: int,
                                     metrics=None, max_pages: int = 500,
                                     delay_ms: int = 750, simulate_fn=None):
    """
    BFS crawl from start_url up to max_depth. If metrics object has a
    `blocked` attribute, crawling stops when blocked is True.
    """
    queue = [(start_url, 0, None)]
    queued = {start_url}
    visited = set()

    while queue and (not metrics or not getattr(metrics, "blocked", False)) and len(visited) < max_pages:
        current_url, current_depth, referrer = queue.pop(0)
        if current_url in visited:
            continue

        if metrics:
            metrics.max_depth_reached = max(getattr(metrics, "max_depth_reached", 0), current_depth)
        log.info("[Depth %d/%d] Visiting %s", current_depth, max_depth, current_url)

        try:
            await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
            visited.add(current_url)
            if metrics and current_url not in getattr(metrics, "visited_endpoints", []):
                metrics.visited_endpoints.append(current_url)
            page = await acknowledge_age_gate_if_present(page, start_url, current_url, simulate_fn)
        except Exception as e:
            log.error("Failed to navigate to %s from %s: %s", current_url, referrer, e)
            continue

        try:
            body_text = await page.locator("body").inner_text()
            if is_likely_blocked(body_text):
                if metrics:
                    metrics.blocked = True
                    metrics.block_time = time.time()
                    metrics.block_reason = f"CAPTCHA/Challenge page detected at {current_url}"
                log.warning("!!! ANTI-BOT DETECTED !!! %s", getattr(metrics, "block_reason", ""))
                break

            links = await extract_internal_links(page, start_url)
            log.info("  Found %d same-domain links.", len(links))
        except Exception as e:
            log.error("Failed to inspect links on %s: %s", current_url, e)
            links = []

        if current_depth < max_depth:
            for link in links:
                if link not in queued and link not in visited:
                    queued.add(link)
                    queue.append((link, current_depth + 1, current_url))

        if simulate_fn:
            await simulate_fn(page)
        elif delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
