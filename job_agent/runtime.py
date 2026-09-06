from __future__ import annotations

from dataclasses import dataclass, field
from job_agent.config import load_config
from job_agent.lmstudio import lms, lms_bin, server_reachable, status


@dataclass
class RuntimeSession:
    started_daemon: bool = False
    started_server: bool = False
    loaded_model: bool = False
    notes: list[str] = field(default_factory=list)


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
        log((up.stdout or up.stderr).strip() or "daemon up")
        session.started_daemon = True

    log(f"Loading {cfg.model}")
    loaded = lms("load", cfg.model, f"--context-length={cfg.context_length}")
    if loaded.returncode != 0:
        loaded = lms("load", cfg.model, "-c", str(cfg.context_length))
    log((loaded.stdout or loaded.stderr).strip() or "model loaded")
    session.loaded_model = loaded.returncode == 0 or cfg.model in (loaded.stdout or "")

    if server_reachable():
        log("LM Studio server already running")
    else:
        log("Starting local server")
        started = lms("server", "start")
        log((started.stdout or started.stderr).strip() or "server start")
        session.started_server = True
    return session


def stop_runtime(session: RuntimeSession | None = None, log=print, *, full_shutdown: bool = True) -> None:
    """Stop the Job Agent LLM mapping.

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
