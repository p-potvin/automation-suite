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


async def run_automation_flow():
    config = load_config()
    targets = config.get('targets', [{'url': 'https://example.com'}])
    target_url = targets[0]['url']
    username_selector = targets[0].get('username_selector', 'input[name="login"]')
    password_selector = targets[0].get('password_selector', 'input[name="password"]')
    submit_selector = targets[0].get('submit_selector', 'input[type="submit"]')

    run_id = f"run_{int(datetime.now().timestamp())}"
    trace_path = os.path.join('logs', f'trace_{run_id}.jsonl')
    recorder = TraceRecorder(trace_path=trace_path, run_id=run_id, base_url=target_url)
    metrics = AntiBotMetrics(platform='automation-suite', mode='stealth')
    mouse_library = load_natural_mouse_path_library()

    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            proxy = await resolve_proxy(session)
            metrics.set_proxy(proxy)

        recorder.record('session-start', targetUrl=target_url, proxy=metrics.proxy)

        context, page, close_fn, provider = await create_stealth_context(p, proxy_config=proxy)
        recorder.record('browser-launched', provider=provider)

        try:
            # Navigate
            log.info("Navigating to %s", target_url)
            await page.goto(target_url, wait_until='domcontentloaded', timeout=45000)
            recorder.record('page-loaded', url=page.url)

            # Handle cookie overlays / age gates
            page = await acknowledge_age_gate_if_present(
                page, expected_origin=target_url, safe_return_url=target_url,
                simulate_fn=lambda pg: Humanizer.simulate_human_behavior(pg, mouse_library)
            )
            recorder.record('age-gate-checked', url=page.url)

            # Human-like delay
            await Humanizer.random_delay(1.0, 3.0)

            # Simulate mouse movement
            await Humanizer.simulate_human_behavior(page, mouse_library)

            # Type credentials
            log.info("Typing credentials...")
            await Humanizer.type_text(page, username_selector, 'test_user_01', 0.1)
            await Humanizer.random_delay(0.5, 1.0)
            await Humanizer.type_text(page, password_selector, 'SecurePass123!', 0.1)
            await Humanizer.random_delay(0.5, 1.0)

            # Click submit
            log.info("Submitting form...")
            await Humanizer.click_element(page, submit_selector)
            await asyncio.sleep(2.0)
            recorder.record('form-submitted', url=page.url)

            # Check for anti-bot block
            try:
                body_text = await page.locator('body').inner_text()
                if is_likely_blocked(body_text):
                    metrics.blocked = True
                    metrics.block_reason = f'CAPTCHA/Challenge detected after submit at {page.url}'
                    recorder.record('anti-bot-detected', reason=metrics.block_reason)
                    log.warning('!!! ANTI-BOT DETECTED !!! %s', metrics.block_reason)
            except Exception:
                pass

            # Extract cookies
            cookies = await page.context.cookies()
            with open('cookies/session.json', 'w') as f:
                json.dump(cookies, f, indent=2)
            log.info('Cookies saved to cookies/session.json (%d cookies)', len(cookies))
            recorder.record('cookies-extracted', count=len(cookies))

            # Optional: crawl the site
            crawl_enabled = os.getenv('CRAWL_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
            if crawl_enabled:
                max_depth = int(os.getenv('CRAWL_MAX_DEPTH', '2'))
                max_pages = int(os.getenv('CRAWL_MAX_PAGES', '20'))
                log.info('Starting BFS crawl (depth=%d, max_pages=%d)', max_depth, max_pages)
                await crawl_links_breadth_first(
                    page, target_url, max_depth, metrics=metrics,
                    max_pages=max_pages,
                    simulate_fn=lambda pg: Humanizer.simulate_human_behavior(pg, mouse_library)
                )
                recorder.record('crawl-complete', visited=len(metrics.visited_endpoints))

        except Exception as e:
            log.error('Error during flow: %s', e)
            recorder.record('flow-error', error=str(e))
        finally:
            artifact_path = metrics.save_artifact()
            recorder.record('session-end', artifact=artifact_path, blocked=metrics.blocked)
            await close_fn()
            log.info('Cleanup complete.')


if __name__ == "__main__":
    print('=' * 50)
    print('Starting Automation Flow')
    print('=' * 50)
    asyncio.run(run_automation_flow())
