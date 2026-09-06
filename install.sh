#!/usr/bin/env bash
# Install Job Agent as a desktop app and set up LM Studio only if needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

if [[ ! -d .venv ]]; then
  echo "==> Creating virtualenv"
  python3 -m venv .venv
fi

echo "==> Installing job-agent"
".venv/bin/python" -m pip install -U pip
".venv/bin/python" -m pip install -e "$ROOT"

echo "==> Running setup"
".venv/bin/job-agent" setup

echo
echo "Installed Job Agent to ~/Applications and your Desktop."
echo "Opening the app…"
echo
if [[ "${SKIP_APP:-}" == "1" ]]; then
  exit 0
fi
".venv/bin/job-agent" launch
