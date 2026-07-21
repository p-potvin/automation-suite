"""
Stealth browser provider abstraction with anti-detection init scripts.
Supports Patchright (fallback), Kameleo, and MultiLogin providers.
Ported from qa-automation's lib/stealth-browser.ts pattern.
"""

import os
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""

STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]

DEFAULT_PROFILE_DIR = os.path.join(os.getcwd(), "browser_profile")


def _get_provider() -> str:
    return os.getenv("STEALTH_PROVIDER", "patchright").lower()


def _get_proxy_config(proxy_config: Optional[dict] = None) -> Optional[dict]:
    if proxy_config:
        return proxy_config
    from proxy_rotation import get_patchright_proxy
    return get_patchright_proxy()


async def create_stealth_context(playwright, proxy_config: Optional[dict] = None,
                               headless: bool = False, session_index: int = 0):
    """
    Create a stealth browser context using the configured provider.
    Returns (context, page, close_fn, provider_name).
    """
    provider = _get_provider()
    proxy = _get_proxy_config(proxy_config)

    if provider == "kameleo":
        return await _create_kameleo_session(playwright, proxy, headless)
    if provider == "multilogin":
        return await _create_multilogin_session(playwright, proxy, headless)
    return await _create_patchright_session(playwright, proxy, headless, session_index)


async def _create_patchright_session(playwright, proxy, headless, session_index=0):
    base_profile = os.getenv("PATCHRIGHT_PROFILE_DIR", DEFAULT_PROFILE_DIR)
    profile_dir = base_profile if session_index == 0 else f"{base_profile}_s{session_index}"
    os.makedirs(profile_dir, exist_ok=True)

    launch_options = {
        "channel": "chrome",
        "headless": headless,
        "args": STEALTH_LAUNCH_ARGS,
        "ignore_default_args": ["--enable-automation"],
    }
    if proxy:
        launch_options["proxy"] = proxy

    context = await playwright.chromium.launch_persistent_context(profile_dir, **launch_options)
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    page = context.pages[0] if context.pages else await context.new_page()

    async def close():
        await context.close()

    log.info("Started Patchright stealth session (profile=%s, session=%d)", profile_dir, session_index)
    return context, page, close, "patchright"


async def _create_kameleo_session(playwright, proxy, headless):
    import aiohttp

    api_url = os.getenv("KAMELEO_API_URL", "http://localhost:5050")
    api_token = os.getenv("KAMELEO_API_TOKEN", "")
    profile_id = os.getenv("KAMELEO_PROFILE_ID", "")

    if not profile_id:
        raise RuntimeError("KAMELEO_PROFILE_ID is required for kameleo provider")

    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    async with aiohttp.ClientSession() as session:
        await session.post(f"{api_url}/profiles/{profile_id}/stop", headers=headers, timeout=30)
        await session.post(f"{api_url}/profiles/{profile_id}/start", headers=headers, timeout=30)

    import asyncio
    await asyncio.sleep(2.5)

    ws_endpoint = f"ws://localhost:5050/patchright/{profile_id}"
    browser = await playwright.chromium.connect_over_cdp(ws_endpoint, timeout=30000)
    context = browser.contexts[0] if browser.contexts else await browser.new_context(
        ignore_https_errors=True, proxy=proxy
    )
    page = context.pages[0] if context.pages else await context.new_page()

    async def close():
        await browser.close()
        async with aiohttp.ClientSession() as session:
            await session.post(f"{api_url}/profiles/{profile_id}/stop", headers=headers, timeout=30)

    log.info("Started Kameleo stealth session (profile=%s)", profile_id)
    return context, page, close, "kameleo"


async def _create_multilogin_session(playwright, proxy, headless):
    from multilogin_client import MultiLoginClient

    client = MultiLoginClient()
    profile_id = client.create_profile()
    if not profile_id:
        raise RuntimeError("MultiLogin profile creation failed")

    browser_id, browser_url = client.launch_browser(profile_id)
    if not browser_url:
        raise RuntimeError("MultiLogin browser launch failed")

    browser = await playwright.chromium.connect_over_cdp(browser_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context(
        ignore_https_errors=True, proxy=proxy
    )
    page = context.pages[0] if context.pages else await context.new_page()

    async def close():
        await browser.close()
        client.close_session(profile_id)

    log.info("Started MultiLogin stealth session (profile=%s)", profile_id)
    return context, page, close, "multilogin"
