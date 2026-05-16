#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import yaml


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return value


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append_log(path: str, line: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _safe_compare(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return False


def _verify_github_signature(secret: str, body: bytes, sig_header: str | None) -> bool:
    if not sig_header:
        return False
    if not sig_header.startswith("sha256="):
        return False
    received = sig_header[len("sha256=") :].strip()
    computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _safe_compare(received, computed)


def _load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError("Config root must be a mapping")
    return data


def _run_command(command: str, env: dict[str, str], log_path: str) -> tuple[int, str]:
    # Run via bash -lc so deploy scripts can rely on PATH, etc.
    started = _now_iso()
    _append_log(log_path, f"[{started}] run: {command}")
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            text=True,
            capture_output=True,
            env={**os.environ, **env},
            timeout=60 * 30,
        )
        finished = _now_iso()
        out = (proc.stdout or "") + (proc.stderr or "")
        _append_log(log_path, f"[{finished}] exit={proc.returncode}")
        if out.strip():
            _append_log(log_path, out.rstrip("\n"))
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        finished = _now_iso()
        _append_log(log_path, f"[{finished}] exit=124 timeout")
        return 124, "timeout"
    except Exception as e:
        finished = _now_iso()
        _append_log(log_path, f"[{finished}] exit=1 exception={type(e).__name__} {e}")
        return 1, f"{type(e).__name__}: {e}"


def _notify_on_error(cfg: dict[str, Any], title: str, body: str, log_path: str) -> None:
    notifications = cfg.get("notifications")
    cmd = ""
    if isinstance(notifications, dict):
        raw = notifications.get("on_error_command")
        if isinstance(raw, str):
            cmd = raw
    if not cmd:
        return
    env = {"VW_NOTIFY_TITLE": title, "VW_NOTIFY_BODY": body}
    _append_log(log_path, f"[{_now_iso()}] notify: {cmd}")
    subprocess.run(["bash", "-lc", cmd], env={**os.environ, **env}, capture_output=True, text=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "vw-deployd/0.1"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            _json_response(self, 200, {"ok": True, "ts": _now_iso()})
            return
        _json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        cfg_path = _env("VW_DEPLOYD_CONFIG", "/etc/vw-deployd/config.yml")
        log_path = _env("VW_DEPLOYD_LOG", "/var/log/vw-deployd.log")
        secret = _env("VW_GITHUB_WEBHOOK_SECRET")

        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length > 0 else b""

        delivery = self.headers.get("X-GitHub-Delivery", "")
        event = self.headers.get("X-GitHub-Event", "")
        sig = self.headers.get("X-Hub-Signature-256")

        if self.path.rstrip("/") != "/github":
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return

        if event == "ping":
            _json_response(self, 200, {"ok": True, "pong": True})
            return

        if not _verify_github_signature(secret, body, sig):
            _append_log(log_path, f"[{_now_iso()}] deny: bad_signature delivery={delivery} event={event}")
            _json_response(self, 401, {"ok": False, "error": "bad_signature"})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"ok": False, "error": "invalid_json"})
            return

        try:
            cfg = _load_config(cfg_path)
        except Exception as e:
            _append_log(log_path, f"[{_now_iso()}] config_error: {e}")
            _json_response(self, 500, {"ok": False, "error": "config_error"})
            return

        if event != "push":
            _json_response(self, 202, {"ok": True, "ignored": True, "reason": f"event={event}"})
            return

        repo = (payload.get("repository") or {}).get("full_name") or ""
        ref = payload.get("ref") or ""
        after = payload.get("after") or ""

        if not repo or not ref or not after:
            _json_response(self, 400, {"ok": False, "error": "missing_fields"})
            return

        allowed_owners = None
        if isinstance(cfg.get("server"), dict):
            allowed_owners = cfg["server"].get("allowed_owners")
        if isinstance(allowed_owners, list) and allowed_owners:
            owner = repo.split("/", 1)[0]
            if owner not in allowed_owners:
                _json_response(self, 403, {"ok": False, "error": "owner_not_allowed"})
                return

        targets = cfg.get("targets") or {}
        if not isinstance(targets, dict) or repo not in targets:
            _json_response(self, 202, {"ok": True, "ignored": True, "reason": "repo_not_configured"})
            return

        target = targets[repo] or {}
        if not isinstance(target, dict):
            _json_response(self, 500, {"ok": False, "error": "bad_target_config"})
            return

        expected_branch = target.get("branch") or "main"
        expected_ref = f"refs/heads/{expected_branch}"
        if ref != expected_ref:
            _json_response(self, 202, {"ok": True, "ignored": True, "reason": f"ref={ref}"})
            return

        command = target.get("command")
        if not isinstance(command, str) or not command.strip():
            _json_response(self, 500, {"ok": False, "error": "missing_command"})
            return

        env = {
            "VW_REPO_FULL_NAME": repo,
            "VW_REF": ref,
            "VW_AFTER": after,
            "VW_DELIVERY": delivery,
            "VW_EVENT": event,
        }

        _append_log(log_path, f"[{_now_iso()}] push: repo={repo} ref={ref} after={after} delivery={delivery}")
        code, out = _run_command(command, env, log_path)
        if code != 0:
            _notify_on_error(cfg, f"Deploy failed: {repo}", f"exit={code}\n{out[-2000:]}", log_path)
            _json_response(self, 500, {"ok": False, "error": "deploy_failed", "exit": code})
            return

        _json_response(self, 200, {"ok": True, "deployed": True, "repo": repo, "after": after})

    def log_message(self, format: str, *args: Any) -> None:
        # Silence the default noisy access logs; we log important events ourselves.
        return


def main() -> int:
    bind = _env("VW_DEPLOYD_BIND", "127.0.0.1:9033")
    host, port_str = bind.rsplit(":", 1)
    port = int(port_str)

    httpd = HTTPServer((host, port), Handler)
    print(f"vw-deployd listening on http://{host}:{port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
