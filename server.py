"""Serve the Headroom page on this Mac.

The server listens on 127.0.0.1 unless phone access is turned on.
Phone access has no password. Do not publish that address on the internet.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import usage

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8737"))
LOGO_NAMES = {"chatgpt.png", "claude.png", "grok.png", "gemini.png"}
FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/icon-180.png": "icon-180.png",
    "/icon-512.png": "icon-512.png",
}
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
}

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "body": None}
_lan = False


def lan_enabled(argv: list[str] | None = None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    if "--lan" in args:
        return True
    return os.environ.get("HEADROOM_LAN", "").strip().lower() in {"1", "true", "yes"}


def listen_host(argv: list[str] | None = None) -> str:
    return "0.0.0.0" if lan_enabled(argv) else "127.0.0.1"


def logo_path(url_path: str) -> Path | None:
    prefix = "/logos/"
    if not url_path.startswith(prefix):
        return None
    name = url_path[len(prefix):]
    if name not in LOGO_NAMES:
        return None
    return ROOT / "assets" / "logos" / name


def lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def snapshot(fresh: bool = False) -> dict:
    now = time.time()
    with _lock:
        cached = _cache["body"]
        if not fresh and cached and now - _cache["at"] < 20:
            return cached
    jobs = (usage.fetch_chatgpt, usage.fetch_claude, usage.fetch_grok, usage.fetch_gemini)
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        providers = list(pool.map(lambda fn: fn(), jobs))
    ip = lan_ip() if _lan else None
    body = {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lanURL": f"http://{ip}:{PORT}" if ip else None,
        "providers": providers,
    }
    with _lock:
        _cache["at"] = time.time()
        _cache["body"] = body
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str, cache: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            body = b'{"name":"headroom"}'
            self._send(200, body, "application/json", "no-store")
            return
        if path == "/api/usage":
            fresh = "fresh=1" in self.path
            body = json.dumps(snapshot(fresh=fresh), ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8", "no-store")
            return
        logo = logo_path(path)
        if logo is not None:
            if logo.is_file():
                self._send(200, logo.read_bytes(), "image/png", "no-cache")
            else:
                self._send(404, b"", "text/plain", "no-store")
            return
        name = FILES.get(path)
        if not name:
            self._send(404, b"", "text/plain", "no-store")
            return
        file = STATIC / name
        if not file.is_file():
            self._send(404, b"", "text/plain", "no-store")
            return
        content_type = TYPES.get(file.suffix, "application/octet-stream")
        self._send(200, file.read_bytes(), content_type, "no-cache")


def main() -> None:
    global _lan
    _lan = lan_enabled()
    host = listen_host()
    server = ThreadingHTTPServer((host, PORT), Handler)
    print(f"Headroom  http://127.0.0.1:{PORT}")
    if _lan:
        ip = lan_ip()
        if ip:
            print(f"폰    http://{ip}:{PORT}")
            print("폰 주소에는 비밀번호가 없습니다. 인터넷으로 열지 마세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
