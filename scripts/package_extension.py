#!/usr/bin/env python3
"""Generate Clover icons and a Chrome Web Store upload ZIP."""

from __future__ import annotations

import json
import math
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
SIZES = (16, 32, 48, 128)
INCLUDED = {
    "manifest.json",
    "background.js",
    "content.js",
    "sidepanel.html",
    "sidepanel.js",
    "styles.css",
    "README.md",
    "PRIVACY.md",
}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF
    )


def _inside_round_rect(x: float, y: float, size: int, radius: float) -> bool:
    nearest_x = min(max(x, radius), size - radius)
    nearest_y = min(max(y, radius), size - radius)
    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius**2


def icon_png(size: int) -> bytes:
    scale = 4
    large = size * scale
    pixels = bytearray()
    circles = [
        (0.39, 0.39), (0.61, 0.39), (0.39, 0.61), (0.61, 0.61)
    ]
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            samples = [0, 0, 0, 0]
            for sy in range(scale):
                for sx in range(scale):
                    lx = (x * scale + sx + 0.5)
                    ly = (y * scale + sy + 0.5)
                    if not _inside_round_rect(lx, ly, large, large * 0.23):
                        color = (0, 0, 0, 0)
                    else:
                        nx, ny = lx / large, ly / large
                        leaf = any(
                            math.dist((nx, ny), center) <= 0.145 for center in circles
                        )
                        stem = (
                            abs(nx - (0.5 + (ny - 0.55) * 0.22)) < 0.035
                            and 0.52 < ny < 0.83
                        )
                        color = (241, 247, 238, 255) if leaf or stem else (55, 111, 79, 255)
                    for channel, value in enumerate(color):
                        samples[channel] += value
            pixels.extend(round(value / (scale * scale)) for value in samples)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + _chunk(b"IEND", b"")
    )


def generate_icons() -> None:
    icons = EXTENSION / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        (icons / f"icon{size}.png").write_bytes(icon_png(size))


def validate_manifest() -> dict[str, object]:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise ValueError("The browser companion must use Manifest V3.")
    version = str(manifest.get("version") or "")
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}", version):
        raise ValueError("The extension manifest has an invalid store version.")
    required = {"background.js", "content.js", "sidepanel.html", "sidepanel.js", "styles.css"}
    missing = sorted(name for name in required if not (EXTENSION / name).is_file())
    if missing:
        raise FileNotFoundError(f"Missing extension files: {', '.join(missing)}")
    return manifest


def package() -> Path:
    generate_icons()
    manifest = validate_manifest()
    version = str(manifest["version"])
    destination = ROOT / "dist" / f"clover-browser-companion-{version}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION.rglob("*")):
            relative = path.relative_to(EXTENSION)
            if not path.is_file():
                continue
            if relative.parts[0] == "icons" or relative.as_posix() in INCLUDED:
                archive.write(path, relative.as_posix())
    stable = destination.with_name("clover-browser-companion.zip")
    stable.write_bytes(destination.read_bytes())
    return destination


if __name__ == "__main__":
    if "--icons-only" in sys.argv:
        generate_icons()
        print(EXTENSION / "icons")
    else:
        print(package())
