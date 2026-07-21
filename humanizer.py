import os
import json
import random
import asyncio
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_MOUSE_PATHS_FILE = os.path.join(os.getcwd(), "test-results", "natural-mouse-paths.json")

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def natural_mouse_paths_enabled() -> bool:
    configured = os.getenv("QA_MOUSE_PATHS_ENABLED")
    if configured is None or configured.strip() == "":
        return True
    normalized = configured.strip().lower()
    if normalized in _FALSE_VALUES:
        return False
    return normalized in _TRUE_VALUES


def load_natural_mouse_path_library() -> Optional[dict]:
    if not natural_mouse_paths_enabled():
        return None
    library_path = os.getenv("QA_MOUSE_PATHS_FILE") or DEFAULT_MOUSE_PATHS_FILE
    if not os.path.exists(library_path):
        return None
    try:
        with open(library_path, "r", encoding="utf8") as f:
            parsed = json.load(f)
    except Exception:
        return None
    if parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("profiles"), list):
        return None
    return parsed


async def replay_natural_mouse_path(page, library=None):
    """Replay a random recorded mouse path on the page. Returns True if replayed."""
    if library is None:
        library = load_natural_mouse_path_library()
    if not library:
        return False
    profiles = library.get("profiles", [])
    if not profiles:
        return False
    profile = random.choice(profiles)
    points = profile.get("points") if isinstance(profile, dict) else None
    if not isinstance(points, list) or len(points) < 2:
        return False
    try:
        viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
    except Exception:
        viewport = {"width": 1280, "height": 720}
    max_x = max(1, int(viewport.get("width", 1280)) - 1)
    max_y = max(1, int(viewport.get("height", 720)) - 1)
    previous_t = float(points[0].get("tMs", 0) or 0)
    for point in points:
        current_t = float(point.get("tMs", previous_t) or previous_t)
        wait_ms = min(250, max(0, current_t - previous_t))
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000)
        await page.mouse.move(float(point.get("x", 0)) * max_x, float(point.get("y", 0)) * max_y)
        previous_t = current_t
    return True


class Humanizer:
    """Human-like interaction helpers with natural mouse path support."""

    @staticmethod
    async def random_delay(min_delay: float, max_delay: float):
        await asyncio.sleep(random.uniform(min_delay, max_delay))

    @staticmethod
    async def replay_mouse_path(page, library=None):
        return await replay_natural_mouse_path(page, library)

    @staticmethod
    async def random_mouse_move(page, x: int, y: int, duration: float = 0.5):
        try:
            viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        except Exception:
            viewport = {"width": 1280, "height": 720}
        for _ in range(random.randint(2, 4)):
            rand_x = random.randint(50, max(51, int(viewport.get("width", 1280)) - 50))
            rand_y = random.randint(50, max(51, int(viewport.get("height", 720)) - 50))
            await page.mouse.move(rand_x, rand_y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.8))
        await page.mouse.move(x, y, steps=random.randint(10, 25))

    @staticmethod
    async def type_text(page, selector: str, text: str, delay: float = 0.1):
        locator = page.locator(selector)
        await locator.fill("")
        for char in text:
            await locator.type(char, delay=delay)
            await asyncio.sleep(random.uniform(0.05, 0.2))

    @staticmethod
    async def click_element(page, selector: str):
        locator = page.locator(selector)
        try:
            box = await locator.bounding_box()
            if box:
                await page.mouse.move(box["x"], box["y"])
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await locator.click()
        except Exception as e:
            log.warning("Click error: %s", e)

    @staticmethod
    async def simulate_human_behavior(page, library=None):
        """Full human simulation: mouse paths, scrolling, random moves."""
        if await replay_natural_mouse_path(page, library):
            log.info("Replayed natural mouse path library sample.")
        try:
            viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        except Exception:
            viewport = {"width": 1280, "height": 720}
        max_x = viewport.get("width", 1280)
        max_y = viewport.get("height", 720)
        for _ in range(random.randint(1, 3)):
            scroll_y = random.randint(100, 500)
            direction = 1 if random.choice([True, False]) else -1
            await page.mouse.wheel(0, scroll_y * direction)
            await asyncio.sleep(random.uniform(0.5, 1.5))
        for _ in range(random.randint(2, 4)):
            x = random.randint(50, max_x - 50)
            y = random.randint(50, max_y - 50)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.8))
        await asyncio.sleep(random.uniform(1.0, 3.0))
