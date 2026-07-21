import os
import json
import asyncio
import logging
from datetime import datetime

from stealth_browser import create_stealth_context
from humanizer import Humanizer, load_natural_mouse_path_library
from page_actions import (
    acknowledge_age_gate_if_present,
    accept_cookie_overlay_if_visible,
    crawl_links_breadth_first,
    is_likely_blocked,
)
from trace_recorder import TraceRecorder, AntiBotMetrics
from proxy_rotation import resolve_proxy

os.makedirs('logs', exist_ok=True)
os.makedirs('cookies', exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_config():
    import yaml
    config_path = 'config/settings.yaml'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {}


async def run_single_session(session_index: int, target_config: dict, playwright=None):
    """Run a single automation session. Designed to be called concurrently."""
    target_url = target_config['url']
    username_selector = target_config.get('username_selector', 'input[name="login"]')
    password_selector = target_config.get('password_selector', 'input[name="password"]')
    submit_selector = target_config.get('submit_selector', 'input[type="submit"]')

    run_id = f"run_{int(datetime.now().timestamp())}_s{session_index}"
    trace_path = os.path.join('logs', f'trace_{run_id}.jsonl')
    recorder = TraceRecorder(trace_path=trace_path, run_id=run_id, base_url=target_url,
                             session_index=session_index)
    metrics = AntiBotMetrics(platform='automation-suite', mode='stealth')
    mouse_library = load_natural_mouse_path_library()

    owns_playwright = False
    if playwright is None:
        from patchright.async_api import async_playwright
        playwright = await async_playwright().start()
        owns_playwright = True

    try:
        import aiohttp
        async with aiohttp.ClientSession() as http_session:
            proxy = await resolve_proxy(http_session, session_index=session_index)
            metrics.set_proxy(proxy)

        recorder.record('session-start', targetUrl=target_url, proxy=metrics.proxy,
                        sessionIndex=session_index)
        log.info("[Session %d] Starting — target=%s proxy=%s", session_index, target_url,
                 metrics.proxy.get('server') if metrics.proxy else 'direct')

        context, page, close_fn, provider = await create_stealth_context(playwright, proxy_config=proxy,
                                                                         session_index=session_index)
        recorder.record('browser-launched', provider=provider, sessionIndex=session_index)

        try:
            # Navigate
            log.info("[Session %d] Navigating to %s", session_index, target_url)
            await page.goto(target_url, wait_until='domcontentloaded', timeout=45000)
            recorder.record('page-loaded', url=page.url, sessionIndex=session_index)

            # Handle cookie overlays / age gates
            page = await acknowledge_age_gate_if_present(
                page, expected_origin=target_url, safe_return_url=target_url,
                simulate_fn=lambda pg: Humanizer.simulate_human_behavior(pg, mouse_library)
            )
            recorder.record('age-gate-checked', url=page.url, sessionIndex=session_index)

            # Human-like delay
            await Humanizer.random_delay(1.0, 3.0)

            # Simulate mouse movement
            await Humanizer.simulate_human_behavior(page, mouse_library)

            # Type credentials
            log.info("[Session %d] Typing credentials...", session_index)
            await Humanizer.type_text(page, username_selector, 'test_user_01', 0.1)
            await Humanizer.random_delay(0.5, 1.0)
            await Humanizer.type_text(page, password_selector, 'SecurePass123!', 0.1)
            await Humanizer.random_delay(0.5, 1.0)

            # Click submit
            log.info("[Session %d] Submitting form...", session_index)
            await Humanizer.click_element(page, submit_selector)
            await asyncio.sleep(2.0)
            recorder.record('form-submitted', url=page.url, sessionIndex=session_index)

            # Check for anti-bot block
            try:
                body_text = await page.locator('body').inner_text()
                if is_likely_blocked(body_text):
                    metrics.blocked = True
                    metrics.block_reason = f'CAPTCHA/Challenge detected after submit at {page.url}'
                    recorder.record('anti-bot-detected', reason=metrics.block_reason, sessionIndex=session_index)
                    log.warning('[Session %d] !!! ANTI-BOT DETECTED !!! %s', session_index, metrics.block_reason)
            except Exception:
                pass

            # Extract cookies
            cookies = await page.context.cookies()
            cookie_file = os.path.join('cookies', f'session_s{session_index}.json')
            with open(cookie_file, 'w') as f:
                json.dump(cookies, f, indent=2)
            log.info('[Session %d] Cookies saved to %s (%d cookies)', session_index, cookie_file, len(cookies))
            recorder.record('cookies-extracted', count=len(cookies), sessionIndex=session_index)

            # Optional: crawl the site
            crawl_enabled = os.getenv('CRAWL_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
            if crawl_enabled:
                max_depth = int(os.getenv('CRAWL_MAX_DEPTH', '2'))
                max_pages = int(os.getenv('CRAWL_MAX_PAGES', '20'))
                log.info('[Session %d] Starting BFS crawl (depth=%d, max_pages=%d)',
                         session_index, max_depth, max_pages)
                await crawl_links_breadth_first(
                    page, target_url, max_depth, metrics=metrics,
                    max_pages=max_pages,
                    simulate_fn=lambda pg: Humanizer.simulate_human_behavior(pg, mouse_library)
                )
                recorder.record('crawl-complete', visited=len(metrics.visited_endpoints),
                                sessionIndex=session_index)

        except Exception as e:
            log.error('[Session %d] Error during flow: %s', session_index, e)
            recorder.record('flow-error', error=str(e), sessionIndex=session_index)
        finally:
            artifact_path = metrics.save_artifact()
            recorder.record('session-end', artifact=artifact_path, blocked=metrics.blocked,
                            sessionIndex=session_index)
            await close_fn()
            log.info('[Session %d] Cleanup complete.', session_index)

    finally:
        if owns_playwright:
            await playwright.stop()


async def run_concurrent_sessions():
    """Run multiple automation sessions concurrently."""
    config = load_config()
    targets = config.get('targets', [{'url': 'https://example.com'}])
    max_sessions = int(os.getenv('MAX_CONCURRENT_SESSIONS', '1'))

    log.info('Starting %d concurrent session(s)', max_sessions)

    from patchright.async_api import async_playwright
    pw = await async_playwright().start()

    try:
        tasks = []
        for i in range(max_sessions):
            target = targets[i % len(targets)]
            tasks.append(run_single_session(i, target, playwright=pw))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error('[Session %d] Crashed: %s', i, result)
            else:
                log.info('[Session %d] Completed successfully', i)
    finally:
        await pw.stop()
        log.info('All sessions finished.')


if __name__ == "__main__":
    print('=' * 50)
    print('Starting Automation Suite')
    print('=' * 50)
    asyncio.run(run_concurrent_sessions())
