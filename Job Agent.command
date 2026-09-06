#!/bin/bash
cd "$(dirname "$0")"
if [[ -x .venv/bin/job-agent ]]; then
  exec .venv/bin/job-agent launch
fi
echo "Job Agent is not installed yet. Run ./install.sh first."
read -n 1 -s -r -p "Press any key to close..."
echo
