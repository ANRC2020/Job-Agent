from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

from job_agent.config import load_config, save_model
from job_agent.lmstudio import downloaded_models, lms, lms_bin, server_reachable, status


@dataclass
class RuntimeSession:
    started_daemon: bool = False
    started_server: bool = False
    loaded_model: bool = False
    notes: list[str] = field(default_factory=list)


def _output(result) -> str:
    return (result.stdout or result.stderr or "").strip()


def _wait_for(check: Callable[[], bool], timeout: float, interval: float = 0.75) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return check()


def _daemon_running() -> bool:
    result = lms("daemon", "status")
    return result.returncode == 0 and "running" in (
        (result.stdout or "") + (result.stderr or "")
    ).lower()


def _model_loaded(model: str) -> bool:
    result = lms("ps")
    return result.returncode == 0 and (
        model in (result.stdout or "") or model.split("/")[-1] in (result.stdout or "")
    )


def start_runtime(log=print) -> RuntimeSession:
    cfg = load_config()
    if lms_bin() is None:
        raise FileNotFoundError("LM Studio CLI is not installed. Run: job-agent setup")
    before = status()
    session = RuntimeSession()

    if before["daemonRunning"]:
        log("LM Studio daemon already running")
    else:
        log("Starting LM Studio daemon")
        up = lms("daemon", "up")
        log(_output(up) or "daemon up")
        if up.returncode != 0:
            raise RuntimeError(f"LM Studio daemon could not start: {_output(up) or 'unknown error'}")
        if not _wait_for(_daemon_running, 30):
            raise RuntimeError("LM Studio daemon did not become ready.")
        session.started_daemon = True

    if before["modelLoaded"]:
        log(f"{cfg.model} is already loaded")
    else:
        log(f"Loading {cfg.model}")
        loaded = lms("load", cfg.model, f"--context-length={cfg.context_length}")
        if loaded.returncode != 0:
            loaded = lms("load", cfg.model, "-c", str(cfg.context_length))
        log(_output(loaded) or "model loaded")
        if loaded.returncode != 0:
            raise RuntimeError(f"Juno's model could not load: {_output(loaded) or 'unknown error'}")
        if not _wait_for(lambda: _model_loaded(cfg.model), 180):
            raise RuntimeError("Juno's model did not finish loading.")
        session.loaded_model = True

    if server_reachable():
        log("LM Studio server already running")
    else:
        log("Starting local server")
        port = urlsplit(cfg.api_base).port or 1234
        started = lms("server", "start", "--port", str(port))
        if started.returncode != 0:
            started = lms("server", "start")
        log(_output(started) or "server start")
        if started.returncode != 0 and not server_reachable():
            raise RuntimeError(
                f"LM Studio's local server could not start: {_output(started) or 'unknown error'}"
            )
        session.started_server = True
    if not _wait_for(server_reachable, 60):
        raise RuntimeError("LM Studio's local server did not become reachable.")
    log("Juno is ready")
    return session


def switch_model(model: str, log=print) -> RuntimeSession:
    name = model.strip()
    if not name:
        raise ValueError("Model is required")
    save_model(name)
    if lms_bin() is None:
        raise FileNotFoundError("LM Studio CLI is not installed. Run setup from Settings.")
    listed = " ".join(downloaded_models())
    if name not in listed and name.split("/")[-1] not in listed:
        log(f"Downloading {name}")
        got = lms("get", name, "--yes")
        if got.returncode != 0:
            raise RuntimeError(got.stderr or got.stdout or "Model download failed")
        log((got.stdout or got.stderr).strip())
    try:
        lms("unload", "--all")
    except Exception:
        pass
    return start_runtime(log)


def stop_runtime(session: RuntimeSession | None = None, log=print, *, full_shutdown: bool = True) -> None:
    """Stop Clover's Juno LLM runtime.

    full_shutdown=True (desktop app): unload model, stop server, stop daemon.
    Otherwise only undo what this process started.
    """
    cfg = load_config()
    if lms_bin() is None:
        log("lms is not installed; nothing to stop")
        return

    if full_shutdown or (session and session.loaded_model):
        log(f"Unloading {cfg.model}")
        unloaded = lms("unload", cfg.model)
        if unloaded.returncode != 0:
            lms("unload", "--all")
        log((unloaded.stdout or unloaded.stderr).strip() or "model unloaded")

    if full_shutdown or (session and session.started_server):
        log("Stopping LM Studio server")
        stopped = lms("server", "stop")
        log((stopped.stdout or stopped.stderr).strip() or "server stop")

    if full_shutdown or (session and session.started_daemon):
        log("Stopping LM Studio daemon")
        down = lms("daemon", "down")
        log((down.stdout or down.stderr).strip() or "daemon down")
