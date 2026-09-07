#!/usr/bin/env bash
# Destructive clean-install test for Clover's app/runtime only.
# Personal Clover data under Application Support is deliberately preserved.
set -euo pipefail

if [[ "${CLOVER_CLEAN_INSTALL_CONFIRM:-}" != "remove-apps-and-models" ]]; then
  echo "Refusing to remove installed apps and models without confirmation." >&2
  echo "Run with CLOVER_CLEAN_INSTALL_CONFIRM=remove-apps-and-models" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Stopping existing Clover and LM Studio processes"
osascript -e 'tell application "Clover" to quit' >/dev/null 2>&1 || true
if [[ -x ".venv/bin/job-agent" ]]; then
  ".venv/bin/job-agent" stop >/dev/null 2>&1 || true
fi
pkill -f "python.*job_agent" >/dev/null 2>&1 || true
pkill -f "LM Studio" >/dev/null 2>&1 || true

echo "==> Removing app/runtime installations (personal Clover data is preserved)"
osascript -e 'tell application "Finder" to delete every item of desktop whose name starts with "Clover"' >/dev/null 2>&1 || true
rm -rf \
  "$HOME/Applications/Clover.app" \
  "$HOME/.lmstudio" \
  "$ROOT/.venv"
rm -rf "/Applications/LM Studio.app" 2>/dev/null || true
if [[ -e "/Applications/LM Studio.app" ]]; then
  echo "Cannot remove /Applications/LM Studio.app without elevated access." >&2
  exit 3
fi

echo "==> Installing from a clean machine state"
SKIP_APP=1 ./install.sh

echo "==> Launching Clover from the installed app"
open "$HOME/Applications/Clover.app"

echo "==> Waiting for Clover and Juno to become ready"
for _attempt in $(seq 1 240); do
  if response="$(curl -fsS http://127.0.0.1:8765/api/readiness 2>/dev/null)" &&
     [[ "$response" == *'"ready": true'* ]]; then
    echo "Clean install passed: Clover launched and Juno is ready."
    exit 0
  fi
  sleep 1
done

echo "Clean install failed: Juno did not become ready within four minutes." >&2
exit 1
