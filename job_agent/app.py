from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from job_agent.branding import apply_app_branding
from job_agent.chat import complete
from job_agent.config import load_config
from job_agent.lmstudio import status
from job_agent.runtime import start_runtime, stop_runtime
from job_agent.setup import run_setup

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_bytes(payload: object, code: int = 200) -> tuple[int, bytes, str]:
    return code, json.dumps(payload).encode("utf-8"), "application/json"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (STATIC_DIR / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/app-icon.png":
            icon = STATIC_DIR / "app-icon.png"
            self._send(200, icon.read_bytes(), "image/png")
            return
        if path == "/api/status":
            code, body, ctype = _json_bytes(status())
            self._send(code, body, ctype)
            return
        self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"invalid json"}', "application/json")
            return
        try:
            if path == "/api/setup":
                logs: list[str] = []
                run_setup(log=logs.append)
                code, body, ctype = _json_bytes({"ok": True, "logs": logs})
                self._send(code, body, ctype)
                return
            if path == "/api/start":
                logs: list[str] = []
                start_runtime(log=logs.append)
                code, body, ctype = _json_bytes({"ok": True, "logs": logs, "status": status()})
                self._send(code, body, ctype)
                return
            if path == "/api/stop":
                logs: list[str] = []
                stop_runtime(log=logs.append, full_shutdown=True)
                code, body, ctype = _json_bytes({"ok": True, "logs": logs, "status": status()})
                self._send(code, body, ctype)
                return
            if path == "/api/chat":
                messages = payload.get("messages") or []
                result = complete(messages)
                code, body, ctype = _json_bytes(result)
                self._send(code, body, ctype)
                return
        except Exception as exc:  # noqa: BLE001
            code, body, ctype = _json_bytes({"error": str(exc)}, 500)
            self._send(code, body, ctype)
            return
        self._send(404, b"Not found", "text/plain")


def _open_fallback_window(url: str) -> None:
    system = sys.platform
    chrome = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
    if system == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Arc", "Brave Browser"):
            if (Path("/Applications") / f"{app}.app").is_dir():
                subprocess.Popen(
                    ["open", "-na", app, "--args", f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
        subprocess.Popen(["open", url])
        return
    if system == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        edge = Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if edge.is_file():
            subprocess.Popen([str(edge), f"--app={url}"])
            return
        webbrowser.open(url)
        return
    if chrome:
        subprocess.Popen([chrome, f"--app={url}"])
        return
    webbrowser.open(url)


def _bind_server(port: int) -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.allow_reuse_address = True
    return httpd, port


def _show_native_window(url: str) -> bool:
    try:
        import webview
    except ImportError:
        return False
    apply_app_branding()
    window = webview.create_window(
        "Job Agent",
        url,
        width=1100,
        height=760,
        min_size=(720, 520),
        text_select=True,
    )
    try:
        window.events.shown += apply_app_branding
    except Exception:
        pass
    webview.start()
    return True


def serve(
    port: int | None = None,
    open_browser: bool = True,
    manage_runtime: bool = True,
) -> None:
    cfg = load_config()
    port = port or cfg.app_port
    httpd, port = _bind_server(port)
    url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    apply_app_branding()
    print(f"Job Agent is running at {url}", flush=True)
    session_holder: dict = {"session": None}
    boot: threading.Thread | None = None

    def _boot() -> None:
        try:
            session_holder["session"] = start_runtime()
        except Exception as exc:  # noqa: BLE001
            print(f"Could not start LM Studio: {exc}", flush=True)

    try:
        if manage_runtime:
            boot = threading.Thread(target=_boot, daemon=True)
            boot.start()
        if open_browser:
            shown = False
            try:
                shown = _show_native_window(url)
            except Exception as exc:  # noqa: BLE001
                print(f"Native window failed ({exc}); opening in the browser.", flush=True)
            if not shown:
                _open_fallback_window(url)
                print("Close this terminal or press Ctrl+C to quit and stop LM Studio.", flush=True)
                try:
                    thread.join()
                except KeyboardInterrupt:
                    print("\nStopped.", flush=True)
        else:
            print("Window disabled. Press Ctrl+C to quit.", flush=True)
            try:
                thread.join()
            except KeyboardInterrupt:
                print("\nStopped.", flush=True)
    finally:
        if boot is not None:
            boot.join(timeout=120)
        if manage_runtime:
            stop_runtime(session_holder.get("session"), full_shutdown=True)
        httpd.shutdown()
        httpd.server_close()
