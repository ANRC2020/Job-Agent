#!/usr/bin/env bash
# Install Job Agent. Bundles its own Python via uv — no system Python needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "==> Installing a local Python runtime (uv)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || {
    echo "Could not install uv. Check https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  }
}

ensure_uv
echo "==> Creating virtualenv"
uv python install 3.12
uv venv .venv --python 3.12 --allow-existing

echo "==> Installing job-agent"
uv pip install --python .venv/bin/python -e "$ROOT"

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
