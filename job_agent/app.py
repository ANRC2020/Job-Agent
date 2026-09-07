from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_agent import events, onboarding, opportunities, person
from job_agent.autonomy import complete_approval, list_pending_actions, resolve_approval
from job_agent.branding import apply_app_branding
from job_agent.chat import stream as chat_stream
from job_agent.config import load_config
from job_agent.context import build_turn_context
from job_agent.documents import save_document_base64, save_pasted_text
from job_agent.home import home_overview
from job_agent.learning import learning_detail
from job_agent.personalization import personalization_data
from job_agent.readiness import readiness, technical_status
from job_agent.reflection import reflection_for_stage
from job_agent.repo_tools import call_tool
from job_agent.runtime import start_runtime, stop_runtime, switch_model
from job_agent.setup import run_setup
from job_agent.storage import (
    add_message,
    add_model_run,
    add_tool_actions,
    ensure_thread,
    initialize_database,
    list_messages,
    list_tool_actions,
    tool_action_status,
    touch_conversation,
)
from job_agent.strategy import strategy_summary

STATIC_DIR = Path(__file__).resolve().parent / "static"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# Tools whose use means an open screen is now out of date.
MUTATING_TOOLS = {
    "save_opportunity",
    "set_opportunity_stage",
    "add_opportunity_note",
    "save_application_material",
    "remember_about_user",
    "note_observation",
    "record_progress",
    "save_experience",
}

MAX_HISTORY_TURNS = 24
MAX_TURN_CHARS = 6_000
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class ClientGone(Exception):
    """The window closed or navigated away mid-response."""


def _thread_for(opportunity_id: str | None) -> str:
    if opportunity_id:
        return opportunities.thread_id(opportunity_id)
    return ensure_thread(kind="juno", title="Juno")


def _serialized_chat(method):
    """Prevent overlapping model runs from interleaving one durable thread."""
    def wrapped(self, payload: dict[str, Any]) -> None:
        opportunity_id = str(payload.get("opportunityId") or "").strip() or None
        thread_id = _thread_for(opportunity_id)
        with _THREAD_LOCKS_GUARD:
            lock = _THREAD_LOCKS.setdefault(thread_id, threading.Lock())
        if not lock.acquire(blocking=False):
            self._json(
                {"error": "Juno is still finishing the previous message in this conversation."},
                409,
            )
            return
        try:
            method(self, {**payload, "_threadId": thread_id})
        finally:
            lock.release()

    return wrapped


def _model_messages(thread_id: str) -> list[dict[str, str]]:
    """Rebuild the conversation from storage, so context survives restarts."""
    history = list_messages(thread_id, limit=MAX_HISTORY_TURNS * 2)[-MAX_HISTORY_TURNS:]
    return [
        {"role": str(item["role"]), "content": str(item["content"])[:MAX_TURN_CHARS]}
        for item in history
        if str(item["content"]).strip()
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    # --- plumbing ---------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR)
        except ValueError:
            self._send(403, b"Forbidden", "text/plain")
            return
        if not target.is_file():
            # Unknown paths belong to the client-side router.
            target = STATIC_DIR / "index.html"
        content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), content_type)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._serve_static(parsed.path)
            return
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self._dispatch(self._segments(parsed.path), query, self.GET_ROUTES)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "Clover couldn't read that request."}, 400)
            return
        if not isinstance(payload, dict):
            payload = {}
        self._dispatch(self._segments(parsed.path), payload, self.POST_ROUTES)

    @staticmethod
    def _segments(path: str) -> list[str]:
        return [segment for segment in path[len("/api/") :].split("/") if segment]

    def _dispatch(
        self,
        segments: list[str],
        payload: dict[str, Any],
        routes: dict[tuple[str, ...], str],
    ) -> None:
        for pattern, method_name in routes.items():
            params = _match(pattern, segments)
            if params is None:
                continue
            try:
                getattr(self, method_name)(payload, **params)
            except ClientGone:
                return
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                print(f"Clover API error: {exc}", file=sys.stderr, flush=True)
                self._json({"error": "Clover couldn't complete that request."}, 500)
            return
        self._json({"error": "Not found"}, 404)

    # --- reads ------------------------------------------------------------

    def get_bootstrap(self, query: dict[str, Any]) -> None:
        self._json(
            {
                "readiness": readiness(),
                "onboarding": onboarding.onboarding_state(),
            }
        )

    def get_readiness(self, query: dict[str, Any]) -> None:
        try:
            attempts = int(query.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        self._json(readiness(attempts=attempts))

    def get_home(self, query: dict[str, Any]) -> None:
        self._json(home_overview())

    def get_opportunities(self, query: dict[str, Any]) -> None:
        self._json(opportunities.list_opportunities())

    def get_opportunity(self, query: dict[str, Any], opportunity_id: str = "") -> None:
        detail = opportunities.get_opportunity(opportunity_id)
        if detail is None:
            self._json({"error": "That opportunity isn't in Clover anymore."}, 404)
            return
        self._json(detail)

    def get_profile(self, query: dict[str, Any]) -> None:
        self._json(person.profile_overview())

    def get_onboarding(self, query: dict[str, Any]) -> None:
        self._json(onboarding.onboarding_state())

    def get_thread(self, query: dict[str, Any]) -> None:
        thread_id = ensure_thread(kind="juno", title="Juno")
        self._json(
            {
                "threadId": thread_id,
                "messages": list_messages(thread_id),
                "actions": list_tool_actions(thread_id),
            }
        )

    def get_learning(self, query: dict[str, Any], learning_id: str = "") -> None:
        detail = learning_detail(learning_id)
        if detail is None:
            self._json({"error": "That observation is no longer in Clover."}, 404)
            return
        self._json(detail)

    def get_settings(self, query: dict[str, Any]) -> None:
        self._json(
            {
                "personalization": personalization_data(),
                "pendingActions": list_pending_actions(),
                "engine": technical_status(),
            }
        )

    def get_strategy(self, query: dict[str, Any]) -> None:
        self._json(strategy_summary())

    # --- writes -----------------------------------------------------------

    def post_onboarding_answer(self, payload: dict[str, Any]) -> None:
        self._json(
            onboarding.answer(
                str(payload.get("step") or ""),
                str(payload.get("value") or ""),
                skipped=bool(payload.get("skipped")),
            )
        )

    def post_onboarding_finish(self, payload: dict[str, Any]) -> None:
        self._json(onboarding.finish())

    def post_document(self, payload: dict[str, Any]) -> None:
        self._json(
            save_document_base64(
                filename=str(payload.get("filename") or "resume"),
                content=str(payload.get("content") or ""),
                kind=str(payload.get("kind") or "resume"),
            )
        )

    def post_document_paste(self, payload: dict[str, Any]) -> None:
        self._json(save_pasted_text(text=str(payload.get("text") or "")))

    def post_opportunity(self, payload: dict[str, Any]) -> None:
        result = opportunities.save_opportunity(
            title=str(payload.get("role") or ""),
            company=str(payload.get("company") or ""),
            description=str(payload.get("jobDescription") or ""),
            source_url=str(payload.get("sourceUrl") or ""),
            stage=str(payload.get("stage") or "interested"),
        )
        self._json(result)

    def post_opportunity_stage(self, payload: dict[str, Any], opportunity_id: str = "") -> None:
        stage = str(payload.get("stage") or "")
        result = events.transition_stage(
            opportunity_id,
            stage,
            reason=str(payload.get("reason") or ""),
            outcome=str(payload.get("outcome") or ""),
        )
        result["reflection"] = reflection_for_stage(opportunity_id, stage)
        self._json(result)

    def post_opportunity_note(self, payload: dict[str, Any], opportunity_id: str = "") -> None:
        note_id = events.record_interaction(
            opportunity_id,
            str(payload.get("text") or ""),
            kind=str(payload.get("kind") or "note"),
        )
        self._json({"id": note_id})

    def post_opportunity_reaction(self, payload: dict[str, Any], opportunity_id: str = "") -> None:
        events.record_reaction(opportunity_id, str(payload.get("reaction") or ""))
        self._json({"ok": True})

    def post_fact_dismiss(self, payload: dict[str, Any], fact_id: str = "") -> None:
        person.dismiss_fact(fact_id)
        self._json({"ok": True})

    def post_observation_review(self, payload: dict[str, Any], observation_id: str = "") -> None:
        person.review_observation(
            observation_id,
            str(payload.get("verdict") or ""),
            edited_claim=str(payload.get("claim") or ""),
            note=str(payload.get("note") or ""),
        )
        self._json({"ok": True})

    def post_approval(self, payload: dict[str, Any], action_id: str = "") -> None:
        resolution = resolve_approval(action_id, bool(payload.get("approved")))
        if not resolution["approved"]:
            self._json({"ok": True, "status": "rejected"})
            return
        result = call_tool(
            str(resolution["actionName"]),
            resolution["arguments"],
            approval_granted=True,
        )
        succeeded = not result.startswith(("Tool error:", "Unknown tool:"))
        complete_approval(action_id, succeeded=succeeded)
        self._json(
            {
                "ok": succeeded,
                "status": "completed" if succeeded else "failed",
                "result": result if succeeded else "The approved action could not be completed.",
            },
            200 if succeeded else 500,
        )

    def post_engine(self, payload: dict[str, Any], action: str = "") -> None:
        logs: list[str] = []
        if action == "setup":
            run_setup(log=logs.append)
        elif action == "start":
            start_runtime(log=logs.append)
        elif action == "stop":
            stop_runtime(log=logs.append, full_shutdown=True)
        elif action == "model":
            switch_model(str(payload.get("model") or ""), log=logs.append)
        else:
            self._json({"error": "Unknown action"}, 404)
            return
        self._json({"ok": True, "logs": logs, "engine": technical_status()})

    # --- Juno's turn ------------------------------------------------------

    @_serialized_chat
    def post_chat(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message") or "").strip()
        opportunity_id = str(payload.get("opportunityId") or "").strip() or None
        if not message:
            self._json({"error": "Nothing to send."}, 400)
            return

        thread_id = str(payload["_threadId"])
        add_message(thread_id, "user", message)
        history = _model_messages(thread_id)
        context = build_turn_context(
            conversation_id=thread_id,
            process_id=opportunity_id,
            task=message,
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event: dict[str, Any]) -> None:
            try:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ClientGone from exc

        emit({"type": "thread", "threadId": thread_id})
        started = time.monotonic()
        result: dict[str, Any] = {}
        try:
            for event in chat_stream(history, context=context, opportunity_id=opportunity_id):
                if event["type"] == "done":
                    result = event
                    continue
                emit(event)
        except ClientGone:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"Juno chat error: {exc}", file=sys.stderr, flush=True)
            emit(
                {
                    "type": "error",
                    "message": (
                        "Juno couldn't finish that thought. She may still be waking up — "
                        "give it a moment and try again."
                    ),
                }
            )
            emit({"type": "end"})
            return

        content = str(result.get("content") or "").strip()
        traces = result.get("tools") or []
        used = {trace.get("tool") for trace in traces}
        kept = None
        if opportunity_id and content and "save_application_material" not in used:
            try:
                kept = opportunities.keep_unsaved_draft(opportunity_id, content)
            except Exception:  # noqa: BLE001 - a missed draft must not break the reply
                kept = None
        if content:
            run_id = add_model_run(
                provider="lm-studio",
                model=str(result.get("model") or load_config().model),
                output=result,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            add_message(thread_id, "assistant", content, model_run_id=run_id)
            add_tool_actions(thread_id, run_id, traces)
        else:
            touch_conversation(thread_id)
        emit(
            {
                "type": "end",
                "content": content,
                "changed": bool(kept) or any(trace.get("tool") in MUTATING_TOOLS for trace in traces),
                "activity": [trace.get("activity") for trace in traces],
                "actions": [
                    {
                        "tool": trace.get("tool"),
                        "activity": trace.get("activity"),
                        "status": tool_action_status(str(trace.get("result") or "")),
                    }
                    for trace in traces
                ],
            }
        )

    GET_ROUTES: dict[tuple[str, ...], str] = {
        ("bootstrap",): "get_bootstrap",
        ("readiness",): "get_readiness",
        ("home",): "get_home",
        ("opportunities",): "get_opportunities",
        ("opportunities", ":opportunity_id"): "get_opportunity",
        ("profile",): "get_profile",
        ("learnings", ":learning_id"): "get_learning",
        ("onboarding",): "get_onboarding",
        ("thread",): "get_thread",
        ("settings",): "get_settings",
        ("strategy",): "get_strategy",
    }

    POST_ROUTES: dict[tuple[str, ...], str] = {
        ("chat",): "post_chat",
        ("onboarding", "answer"): "post_onboarding_answer",
        ("onboarding", "finish"): "post_onboarding_finish",
        ("documents",): "post_document",
        ("documents", "paste"): "post_document_paste",
        ("opportunities",): "post_opportunity",
        ("opportunities", ":opportunity_id", "stage"): "post_opportunity_stage",
        ("opportunities", ":opportunity_id", "note"): "post_opportunity_note",
        ("opportunities", ":opportunity_id", "reaction"): "post_opportunity_reaction",
        ("profile", "facts", ":fact_id", "dismiss"): "post_fact_dismiss",
        ("profile", "observations", ":observation_id", "review"): "post_observation_review",
        ("approvals", ":action_id"): "post_approval",
        ("engine", ":action"): "post_engine",
    }


def _match(pattern: tuple[str, ...], segments: list[str]) -> dict[str, str] | None:
    if len(pattern) != len(segments):
        return None
    params: dict[str, str] = {}
    for expected, actual in zip(pattern, segments):
        if expected.startswith(":"):
            params[expected[1:]] = actual
        elif expected != actual:
            return None
    return params


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
        "Clover",
        url,
        width=1180,
        height=820,
        min_size=(880, 620),
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
    initialize_database()
    cfg = load_config()
    port = port or cfg.app_port
    httpd, port = _bind_server(port)
    url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    apply_app_branding()
    print(f"Clover is running at {url}", flush=True)
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


app_status = technical_status
