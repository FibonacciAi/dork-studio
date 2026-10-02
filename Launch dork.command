#!/bin/zsh
set -euo pipefail
DORK_RELEASE_ROOT="${0:A:h}"
cd "$DORK_RELEASE_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  print 'Run Setup dork.command once, then open this launcher again.'
  exit 1
fi
exec .venv/bin/python app/dashboard.py --open --port 5357
