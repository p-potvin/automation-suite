"""
Structured trace recording for browser automation sessions.
Ported from qa-automation's lib/qa-run-trace.mjs pattern.
Records every action as JSONL trace events with timestamps and tab snapshots.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


class TraceRecorder:
    """Records structured JSONL trace events for a browser session."""

    def __init__(self, trace_path: Optional[str] = None, run_id: Optional[str] = None,
                 base_url: Optional[str] = None, session_index: Optional[int] = None):
        self.trace_path = trace_path
        self.run_id = run_id
        self.base_url = base_url
        self.session_index = session_index
        self.started_at_ms = time.time() * 1000
        self.events = []

        if trace_path:
            os.makedirs(os.path.dirname(trace_path) or ".", exist_ok=True)
            with open(trace_path, "w", encoding="utf8") as f:
                pass

    def record(self, event_type: str, **payload):
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": event_type,
            "runId": self.run_id,
            "baseUrl": self.base_url,
            "sessionIndex": self.session_index,
            "elapsedMs": round(time.time() * 1000 - self.started_at_ms, 2),
            **payload,
        }
        self.events.append(event)
        if self.trace_path:
            try:
                with open(self.trace_path, "a", encoding="utf8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                log.warning("Failed to write trace event: %s", e)
        return event

    async def page_info(self, page):
        if not page:
            return None
        url = page.url
        title = await page.title().catch(lambda: "") if hasattr(page.title, "catch") else ""
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        except Exception:
            viewport = None
        return {"url": url, "title": title, "viewport": viewport}

    async def get_pages_snapshot(self, context, origin: str = None):
        pages = context.pages
        snapshots = []
        for i, page in enumerate(pages):
            info = await self.page_info(page)
            classification = None
            if origin and info:
                from page_actions import classify_page_url
                classification = classify_page_url(info.get("url", ""), origin)
            snapshots.append({"index": i, **(info or {}), "classification": classification})
        return snapshots


class AntiBotMetrics:
    """Tracks QA run telemetry — block detection, visited endpoints, timing."""

    def __init__(self, platform: str = "automation-suite", profile_id: str = "",
                 mode: str = "stealth"):
        self.platform = platform
        self.profile_id = profile_id
        self.mode = mode
        self.start_time = time.time()
        self.block_time = None
        self.max_depth_reached = 0
        self.successful_endpoints = []
        self.visited_endpoints = []
        self.block_reason = None
        self.blocked = False
        self.proxy = None
        self.bytes_received = 0
        self.bytes_sent = 0

    def set_proxy(self, proxy):
        try:
            if not proxy:
                self.proxy = None
                return
            server = proxy.get("server", "")
            self.proxy = {
                "server": server,
                "username": "redacted" if proxy.get("username") else "",
                "password": "redacted" if proxy.get("password") else "",
            }
        except Exception:
            self.proxy = {"server": "redacted", "username": "", "password": ""}

    def check_response(self, response):
        status = response.status
        url = response.url
        if status in [200, 201, 202, 204, 301, 302, 304, 307, 308]:
            if url not in self.successful_endpoints:
                self.successful_endpoints.append(url)
        elif status in [403, 429]:
            if not self.blocked:
                self.blocked = True
                self.block_time = time.time()
                self.block_reason = f"HTTP {status} at {url}"
                log.warning("!!! ANTI-BOT BLOCK DETECTED !!! %s", self.block_reason)

    def save_artifact(self, output_dir: str = "test-results/artifacts"):
        end_t = self.block_time if self.block_time else time.time()
        ttb = end_t - self.start_time

        artifact = {
            "schemaVersion": 1,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "platform": self.platform,
            "profile_id": self.profile_id,
            "mode": self.mode,
            "time_to_block_seconds": round(ttb, 2),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "max_depth_reached": self.max_depth_reached,
            "visited_endpoints_count": len(self.visited_endpoints),
            "visited_endpoints": self.visited_endpoints,
            "successful_endpoints_count": len(self.successful_endpoints),
            "successful_endpoints": self.successful_endpoints,
            "proxy": self.proxy,
            "estimated_bytes_received": self.bytes_received,
            "estimated_bytes_sent": self.bytes_sent,
        }

        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(
            output_dir,
            f"run_{int(time.time())}_{self.platform}_{self.mode}.json",
        )
        with open(filename, "w", encoding="utf8") as f:
            json.dump(artifact, f, indent=4, ensure_ascii=False)

        log.info("Artifact saved to %s", filename)
        return filename
