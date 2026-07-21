import os
import logging

os.makedirs('logs', exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


class BrowserController:
    """Connects to a browser session via CDP endpoint URL."""

    def __init__(self, browser_url: str):
        self.browser_url = browser_url
        self._playwright = None
        self._browser = None
        self._page = None
        self._close_fn = None

    async def connect(self, playwright=None):
        """Connects to the browser session via CDP. Returns the active page."""
        if playwright is None:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            pw = self._playwright
        else:
            pw = playwright

        try:
            self._browser = await pw.chromium.connect_over_cdp(self.browser_url)
            context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = context.pages[0] if context.pages else await context.new_page()
            log.info("Connected to Browser Session")
            return self._page
        except Exception as e:
            log.error(f"Connection Error: {e}")
            return None

    async def close(self):
        """Closes the connection."""
        try:
            if self._close_fn:
                await self._close_fn()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            log.info("Browser Session Closed")
        except Exception as e:
            log.error(f"Close Error: {e}")

    async def extract_cookies(self):
        """Extracts cookies from the page."""
        cookies = await self._page.context.cookies()
        log.info(f"Extracted {len(cookies)} cookies")
        return cookies
