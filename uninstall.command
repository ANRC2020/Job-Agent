#!/bin/bash
# Uninstall Clover while preserving personal data unless explicitly requested.
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
INSTALL_ROOT="$ROOT"

# A person may run this from a newly downloaded ZIP after installing an older
# version elsewhere. Recover that original folder from the installed app.
for app in "$HOME/Applications/Clover.app" "$HOME/Applications/Job Agent.app"; do
  [[ -d "$app/Contents/MacOS" ]] || continue
  for launcher in "$app/Contents/MacOS/"*; do
    [[ -f "$launcher" ]] || continue
    root_line="$(grep -m 1 '^ROOT=' "$launcher" 2>/dev/null || true)"
    discovered="${root_line#ROOT=\"}"
    discovered="${discovered%\"}"
    if [[ "$discovered" != "$root_line" && -d "$discovered/.venv" ]]; then
      INSTALL_ROOT="$discovered"
      break 2
    fi
  done
done
VENV="$INSTALL_ROOT/.venv"

echo "Clover Uninstaller"
echo
echo "This removes the Clover app, shortcuts, and its private Python environment."
echo "LM Studio will remain installed because other local apps may use it."
echo

if [[ "${CLOVER_UNINSTALL_SMOKE_TEST:-}" != "1" ]]; then
  if [[ -x "$VENV/bin/job-agent" ]]; then
    "$VENV/bin/job-agent" stop >/dev/null 2>&1 || true
  fi

  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
  done < <(pgrep -f "$VENV/bin/python.*job_agent" 2>/dev/null || true)

  osascript -e '
tell application "Finder"
  delete every item of desktop whose name starts with "Clover"
  delete every item of desktop whose name starts with "Job Agent"
end tell
' >/dev/null 2>&1 || true
fi

rm -rf "$HOME/Applications/Clover.app" "$HOME/Applications/Job Agent.app"
rm -rf "$VENV"

REMOVE_DATA="${CLOVER_UNINSTALL_REMOVE_DATA:-ask}"
if [[ "$REMOVE_DATA" == "ask" ]]; then
  echo "Keep your profile, conversations, opportunities, and application history?"
  read -r -p "Keep personal data? [Y/n] " answer
  case "${answer:-Y}" in
    n|N|no|NO|No) REMOVE_DATA="1" ;;
    *) REMOVE_DATA="0" ;;
  esac
fi

if [[ "$REMOVE_DATA" == "1" ]]; then
  rm -rf \
    "$HOME/Library/Application Support/Clover" \
    "$HOME/Library/Application Support/Job Agent"
  echo
  echo "Clover and its personal data were removed."
else
  echo
  echo "Clover was removed. Your personal data was preserved for a future reinstall."
fi

echo "You can now delete this downloaded Job-Agent folder."
echo
if [[ -z "${CI:-}" ]]; then
  read -r -p "Press Return to close." _ </dev/tty 2>/dev/null || true
fi
