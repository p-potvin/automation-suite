"""
Proxy rotation utilities — IPoasis residential proxies, Tor/wireproxy,
NordVPN, ExpressVPN, and custom command rotation.
Ported from qa-automation's proxy_utils.py and lib/qa_ipoasis.py.
"""

import os
import socket
import logging
import urllib.parse
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PROXY_URL = os.getenv("PROXY_URL", "")
IPOASIS_API_KEY = os.getenv("IPOASIS_API_KEY", "")
IPOASIS_KEY_FILE = os.getenv(
    "IPOASIS_API_KEY_FILE",
    r"C:\Users\Administrator\Desktop\ipoasis-promking-automation.txt",
)

TOR_CONTROL_HOST = os.getenv("TOR_CONTROL_HOST", "127.0.0.1")
TOR_CONTROL_PORT = int(os.getenv("TOR_CONTROL_PORT", "9051"))
TOR_CONTROL_PASSWORD = os.getenv("TOR_CONTROL_PASSWORD", "mypassword")
TOR_SOCKS_START_PORT = int(os.getenv("TOR_SOCKS_START_PORT", "20000"))
TOR_SOCKS_PORT_COUNT = int(os.getenv("TOR_SOCKS_PORT_COUNT", "50"))


def send_tor_newnym():
    """Send SIGNAL NEWNYM to Tor control port to request a new IP (circuit rotation)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((TOR_CONTROL_HOST, TOR_CONTROL_PORT))
        sock.sendall(f'AUTHENTICATE "{TOR_CONTROL_PASSWORD}"\r\n'.encode())
        resp = sock.recv(1024)
        if b"250" not in resp:
            log.warning("Tor auth failed: %s", resp.strip())
            sock.close()
            return False
        sock.sendall(b"SIGNAL NEWNYM\r\n")
        resp = sock.recv(1024)
        sock.close()
        if b"250" in resp:
            log.info("Tor IP rotated (NEWNYM signal sent)")
            return True
        log.warning("Tor NEWNYM failed: %s", resp.strip())
        return False
    except Exception as e:
        log.warning("Tor control port connection failed: %s", e)
        return False


def get_tor_socks_port(session_index: int = 0) -> int:
    """Get a Tor SOCKS port for the given session index (round-robin across available ports)."""
    return TOR_SOCKS_START_PORT + (session_index % TOR_SOCKS_PORT_COUNT)


def get_tor_proxy(session_index: int = 0) -> Optional[dict]:
    """Returns Patchright proxy config for a specific Tor SOCKS port."""
    port = get_tor_socks_port(session_index)
    return {
        "server": f"socks5://127.0.0.1:{port}",
    }


def get_requests_proxies():
    """Returns proxy dictionary for Python Requests."""
    if not PROXY_URL:
        return None
    return {"http": PROXY_URL, "https": PROXY_URL}


def get_patchright_proxy() -> Optional[dict]:
    """Returns proxy dictionary for Patchright/Playwright."""
    if not PROXY_URL:
        return None
    parsed = urllib.parse.urlparse(PROXY_URL)
    proxy_config = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    }
    if parsed.username:
        proxy_config["username"] = parsed.username
    if parsed.password:
        proxy_config["password"] = parsed.password
    return proxy_config


def redact_proxy_url(proxy_url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        if not parsed.hostname:
            return "redacted"
        auth = "redacted:redacted@" if parsed.username or parsed.password else ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{auth}{parsed.hostname}{port}"
    except Exception:
        return "redacted"


def read_ipoasis_api_key() -> str:
    if IPOASIS_API_KEY:
        return IPOASIS_API_KEY.strip()
    if IPOASIS_KEY_FILE and os.path.exists(IPOASIS_KEY_FILE):
        with open(IPOASIS_KEY_FILE, "r", encoding="utf8") as f:
            return f.read().strip()
    return ""


async def ipoasis_pick_active_subuser(session, api_key):
    import json

    plans_url = "https://api.ipoasis.com/v1/plans"
    async with session.get(plans_url, headers={"X-API-KEY": api_key}, timeout=30) as resp:
        plans = await resp.json()
    if not isinstance(plans, list) or not plans:
        raise RuntimeError("IPoasis returned no plans.")

    preferred = next((p for p in plans if str(p.get("planType", "")).lower() == "dyn_resi"), plans[0])
    plan_id = preferred.get("id")
    if not plan_id:
        raise RuntimeError("IPoasis plan missing id.")

    sub_url = f"https://api.ipoasis.com/v1/{plan_id}/sub-users"
    async with session.get(sub_url, headers={"X-API-KEY": api_key}, timeout=30) as resp:
        subs = await resp.json()
    if not isinstance(subs, list) or not subs:
        raise RuntimeError("IPoasis returned no sub-users.")

    active = next((s for s in subs if s.get("active") is True), subs[0])
    return {"plan_id": plan_id, "sub_user_id": int(active.get("id"))}


async def ipoasis_get_proxy(session, api_key, sub_user_id, country="US"):
    import json

    url = (
        f"https://api.ipoasis.com/v1/proxy/dynamic/{sub_user_id}"
        f"?country={country}&sessionType=rotate&protocol=http&count=1"
    )
    async with session.get(url, headers={"X-API-KEY": api_key}, timeout=30) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"IPoasis proxy generation failed: HTTP {resp.status}: {text[:200]}")
        data = json.loads(text)
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"IPoasis returned unexpected payload: {text[:200]}")
        return data[0]


def parse_proxy_url(proxy_url: str) -> dict:
    parsed = urllib.parse.urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        raise ValueError(f"Invalid proxy URL: {proxy_url}")
    return {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        "username": parsed.username or "",
        "password": parsed.password or "",
    }


async def fetch_ipoasis_proxy(session, api_key: str, country: str = "US") -> dict:
    """Full IPoasis flow: pick sub-user, generate proxy, parse to Patchright config."""
    sub = await ipoasis_pick_active_subuser(session, api_key)
    proxy_string = await ipoasis_get_proxy(session, api_key, sub["sub_user_id"], country)
    return parse_proxy_url(proxy_string)


async def resolve_proxy(session=None, country: str = "US", session_index: int = 0,
                         rotate_tor: bool = True) -> Optional[dict]:
    """
    Resolve a proxy for the session. Priority:
    1. Tor SOCKS port (per-session port + NEWNYM rotation if rotate_tor)
    2. PROXY_URL env var (static proxy)
    3. IPoasis residential proxy (if API key available)
    4. None (direct connection)
    """
    tor_enabled = os.getenv("TOR_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    if tor_enabled:
        if rotate_tor and session_index > 0:
            send_tor_newnym()
            import asyncio
            await asyncio.sleep(2)
        proxy = get_tor_proxy(session_index)
        log.info("Using Tor SOCKS port %d for session %d", get_tor_socks_port(session_index), session_index)
        return proxy

    proxy = get_patchright_proxy()
    if proxy:
        log.info("Using proxy from PROXY_URL: %s", redact_proxy_url(PROXY_URL))
        return proxy

    api_key = read_ipoasis_api_key()
    if api_key and session:
        try:
            proxy = await fetch_ipoasis_proxy(session, api_key, country)
            log.info("Using IPoasis residential proxy")
            return proxy
        except Exception as e:
            log.warning("IPoasis proxy fetch failed: %s", e)

    log.warning("No proxy available; running direct connection")
    return None
