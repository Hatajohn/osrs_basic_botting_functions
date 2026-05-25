#!/usr/bin/env bash
# Backward-compatible entrypoint — delegates to InfernalEelFishing/run_infernal_eel.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/InfernalEelFishing/run_infernal_eel.sh" "$@"
