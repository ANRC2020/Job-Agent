#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p \
  "$TMP/source" \
  "$TMP/old-source/.venv" \
  "$TMP/home/Applications/Clover.app/Contents/MacOS" \
  "$TMP/home/Library/Application Support/Clover"
cp "$ROOT/uninstall.command" "$TMP/source/uninstall.command"
cat >"$TMP/home/Applications/Clover.app/Contents/MacOS/Clover" <<EOF
#!/bin/bash
ROOT="$TMP/old-source"
EOF
touch "$TMP/home/Library/Application Support/Clover/preserve-me"

HOME="$TMP/home" \
CI=1 \
CLOVER_UNINSTALL_SMOKE_TEST=1 \
CLOVER_UNINSTALL_REMOVE_DATA=0 \
  /bin/bash "$TMP/source/uninstall.command"

test ! -e "$TMP/old-source/.venv"
test ! -e "$TMP/home/Applications/Clover.app"
test -e "$TMP/home/Library/Application Support/Clover/preserve-me"

mkdir -p "$TMP/source/.venv"
HOME="$TMP/home" \
CI=1 \
CLOVER_UNINSTALL_SMOKE_TEST=1 \
CLOVER_UNINSTALL_REMOVE_DATA=1 \
  /bin/bash "$TMP/source/uninstall.command"

test ! -e "$TMP/home/Library/Application Support/Clover"
echo "macOS uninstall smoke test passed"
