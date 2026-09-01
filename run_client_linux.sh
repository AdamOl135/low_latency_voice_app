#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/client/build/linux/x64/debug/bundle"

if [ ! -d "$BUNDLE_DIR" ]; then
    echo "[-] Error: Linux client bundle not found at ${BUNDLE_DIR}" >&2
    exit 1
fi

export LD_LIBRARY_PATH="${BUNDLE_DIR}/lib:${LD_LIBRARY_PATH:-}"
cd "$BUNDLE_DIR"
exec ./low_latency_voice_app "$@"
