#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
  echo 'MacNet Lab targets macOS.' >&2
  exit 1
fi
if [ ! -x .venv/bin/macnet-lab ]; then
  echo 'First run: bash scripts/install-macos.sh' >&2
  exit 1
fi
exec .venv/bin/macnet-lab "$@"
