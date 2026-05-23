#!/usr/bin/env bash
# Backward-compatible entrypoint — delegates to SacredEelFishing/run_sacred_eel.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/SacredEelFishing/run_sacred_eel.sh" "$@"
