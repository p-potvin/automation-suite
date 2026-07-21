"""
Firefox profile discovery and cloning for automation.
Ported from qa-automation's lib/firefox-profile.mjs.
Supports auto-discovery via profiles.ini and explicit path override.
"""

import os
import shutil
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SKIP_DIRS = {"cache2", "startupCache", "minidumps"}
SKIP_FILES = {"parent.lock", "lock", "sessionstore.jsonlz4", "sessionCheckpoints.json", "compatibility.ini"}


def parse_profiles_ini(ini_text: str) -> list:
    profiles = []
    current = None
    for raw_line in ini_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            current = {} if section.lower().startswith("profile") else None
            if current:
                current["section"] = section
                profiles.append(current)
            continue
        if not current:
            continue
        eq = line.find("=")
        if eq < 0:
            continue
        current[line[:eq].strip()] = line[eq + 1:].strip()
    return profiles


def resolve_firefox_profile_dir() -> str:
    explicit = os.getenv("SEARCH_FIREFOX_PROFILE_DIR") or os.getenv("CRAWL_FIREFOX_PROFILE_DIR") or ""
    if explicit:
        resolved = os.path.abspath(explicit)
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"Firefox profile does not exist: {resolved}")
        return resolved

    app_data = os.getenv("APPDATA")
    if not app_data:
        raise RuntimeError("APPDATA is not set; cannot auto-discover Firefox profile")

    profiles_ini = os.path.join(app_data, "Mozilla", "Firefox", "profiles.ini")
    if not os.path.exists(profiles_ini):
        raise FileNotFoundError(f"Could not find Firefox profiles.ini: {profiles_ini}")

    with open(profiles_ini, "r", encoding="utf8") as f:
        profiles = parse_profiles_ini(f.read())

    profile = (
        next((p for p in profiles if p.get("Default") == "1"), None)
        or next((p for p in profiles if "default-release" in (p.get("Path") or "")), None)
        or (profiles[0] if profiles else None)
    )
    if not profile or not profile.get("Path"):
        raise RuntimeError(f"No usable Firefox profile found in: {profiles_ini}")

    profile_path = (
        os.path.join(app_data, "Mozilla", "Firefox", profile["Path"])
        if profile.get("IsRelative") != "0"
        else profile["Path"]
    )
    resolved = os.path.abspath(profile_path)
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Resolved Firefox profile does not exist: {resolved}")
    return resolved


def copy_firefox_profile(source_dir: str, target_dir: str):
    os.makedirs(target_dir, exist_ok=True)

    def copy_tree(src: str, dst: str):
        os.makedirs(dst, exist_ok=True)
        for entry in os.scandir(src):
            src_path = entry.path
            dst_path = os.path.join(dst, entry.name)
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    copy_tree(src_path, dst_path)
                continue
            if not entry.is_file() or entry.name in SKIP_FILES:
                continue
            try:
                shutil.copy2(src_path, dst_path)
            except Exception:
                pass

    copy_tree(source_dir, target_dir)
    log.info("Copied Firefox profile: %s -> %s", source_dir, target_dir)
