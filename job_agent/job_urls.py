"""Shared URL normalization for job sources and application destinations."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
    "trk",
}


def normalize_web_url(value: Any) -> str:
    clean = str(value or "").strip()
    parsed = urlsplit(clean)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("A usable HTTP or HTTPS address is required.")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), "")
    )


def normalize_job_url(value: Any) -> str:
    """Canonical posting URL; application destinations retain their own path."""
    normalized = normalize_web_url(value)
    parsed = urlsplit(normalized)
    path = parsed.path
    for suffix in ("/application", "/apply"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)] or "/"
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
