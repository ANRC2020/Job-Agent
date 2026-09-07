"""Keeping a reasoning model's working-out away from the person using Clover.

Local models often narrate their thinking inside `<think>` tags. That narration
is not something to say to someone who came here for help, and it should not be
stored or fed back into a later turn either — seeing its own leaked tags in the
history encourages a model to keep producing them.
"""

from __future__ import annotations

import re

OPEN_TAGS = ("<think>", "<thinking>")
CLOSE_TAGS = ("</think>", "</thinking>")

THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.DOTALL)
ORPHAN_CLOSE = re.compile(r"</think(?:ing)?>")


def strip_thinking(text: str) -> str:
    """Remove reasoning blocks, including a tag left open at the end."""
    return ORPHAN_CLOSE.sub("", THINK_BLOCK.sub("", text or "")).strip()


def _partial_tag_length(buffer: str, tags: tuple[str, ...]) -> int:
    """How much of the buffer's tail could still turn into one of `tags`."""
    for size in range(min(len(buffer), max(len(tag) for tag in tags) - 1), 0, -1):
        tail = buffer[-size:]
        if any(tag.startswith(tail) for tag in tags):
            return size
    return 0


def _first_tag(buffer: str, tags: tuple[str, ...]) -> tuple[int, str]:
    best, found = -1, ""
    for tag in tags:
        index = buffer.find(tag)
        if index != -1 and (best == -1 or index < best):
            best, found = index, tag
    return best, found


class ThinkingFilter:
    """Drops reasoning blocks from a token stream, tag boundaries and all."""

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    @property
    def thinking(self) -> bool:
        return self._inside

    def feed(self, text: str) -> str:
        self._buffer += text
        visible: list[str] = []
        while self._buffer:
            if self._inside:
                index, tag = _first_tag(self._buffer, CLOSE_TAGS)
                if index == -1:
                    keep = _partial_tag_length(self._buffer, CLOSE_TAGS)
                    self._buffer = self._buffer[len(self._buffer) - keep :] if keep else ""
                    break
                self._buffer = self._buffer[index + len(tag) :]
                self._inside = False
                continue
            # A close tag can arrive with no matching open when a previous
            # round of the same turn ended mid-thought. Drop it either way.
            index, tag = _first_tag(self._buffer, OPEN_TAGS + CLOSE_TAGS)
            if index == -1:
                keep = _partial_tag_length(self._buffer, OPEN_TAGS + CLOSE_TAGS)
                cut = len(self._buffer) - keep
                visible.append(self._buffer[:cut])
                self._buffer = self._buffer[cut:]
                break
            visible.append(self._buffer[:index])
            self._buffer = self._buffer[index + len(tag) :]
            self._inside = tag in OPEN_TAGS
        return "".join(visible)

    def flush(self) -> str:
        if self._inside:
            self._buffer = ""
            return ""
        remaining, self._buffer = self._buffer, ""
        return remaining
