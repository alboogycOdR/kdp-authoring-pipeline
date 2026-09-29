#!/usr/bin/env bash
# Run the KDP Pipeline audit suite.
#
#   bash audit/run_audit.sh                      # against this checkout (the audited baseline)
#   KDP_AUDIT_TARGET=/path/to/patched bash audit/run_audit.sh
#
# Expected: baseline -> every test_KDP_AUD_* FAILS, every test_POS_* PASSES.
#           patched  -> everything PASSES.
# Requires: Python >= 3.12 with `pip install -e ".[dev]"` (no network, no provider, no key).
# Set PYTHON=/path/to/venv/python if pytest is not on the default python3.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
target="${KDP_AUDIT_TARGET:-$(dirname "$here")}"
echo "Audit target: $target"
cd "$(dirname "$here")"
KDP_AUDIT_TARGET="$target" "${PYTHON:-python3}" -m pytest -q -p no:cacheprovider -rA audit/tests "$@" \
  | tee "$here/evidence/tools/last_run.txt" | grep -E '^(PASSED|FAILED|ERROR) |passed|failed' || true
