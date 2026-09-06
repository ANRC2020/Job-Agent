#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

from job_agent.repo_tools import TOOLS, call_tool

PROTOCOL_VERSION = "2024-11-05"


def _send(message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + payload)
    sys.stdout.buffer.flush()


def _read() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _result(request_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": message}})


def handle(request: dict[str, Any]) -> None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "job-agent", "version": "0.1.0"},
            },
        )
        return
    if method == "notifications/initialized" or request_id is None:
        return
    if method == "tools/list":
        _result(
            request_id,
            {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["schema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        )
        return
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        text = call_tool(str(name), arguments)
        _result(request_id, {"content": [{"type": "text", "text": text}]})
        return
    if method == "ping":
        _result(request_id, {})
        return
    _error(request_id, f"Unsupported method: {method}")


def main() -> None:
    while True:
        request = _read()
        if request is None:
            return
        handle(request)


if __name__ == "__main__":
    main()
