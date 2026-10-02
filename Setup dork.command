#!/bin/zsh
set -euo pipefail
DORK_RELEASE_ROOT="${0:A:h}"
cd "$DORK_RELEASE_ROOT"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
print 'Setup complete. Open Launch dork.command to start your local studio.'
