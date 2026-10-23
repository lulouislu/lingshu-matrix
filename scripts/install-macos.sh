#!/bin/bash
# Build and install locally. No sudo, system Python changes or network configuration.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
  echo 'This installer targets macOS. See README for development preview.' >&2
  exit 1
fi
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<22||(a===22&&b<12))throw Error("Node 22.12+ required (macOS 12: use Node 22.x)")'
npm --prefix frontend ci
npm --prefix frontend run build
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .
echo ''
echo 'Installed. Start with: bash scripts/start-macos.command'
echo 'No probes are enabled on first start. No login item has been installed.'
