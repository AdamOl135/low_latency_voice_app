#!/usr/bin/env bash
set -e

# ==============================================================================
# Low-Latency Voice App: Master E2E Test Suite Runner
# Executes complete 4-tier requirement-driven opaque-box E2E test suite.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "================================================================================"
echo " Starting 4-Tier E2E Test Suite for Low-Latency Voice App"
echo " Working Directory: $PROJECT_ROOT"
echo " Python Runtime:    $(python3 --version)"
echo "================================================================================"

python3 "$SCRIPT_DIR/runner.py" --tier all "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo ">> [SUCCESS] 4-Tier E2E Test Suite passed completely with Exit Code 0."
else
    echo ""
    echo ">> [FAILURE] 4-Tier E2E Test Suite encountered failures (Exit Code: $EXIT_CODE)."
fi

exit $EXIT_CODE

