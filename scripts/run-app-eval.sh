#!/usr/bin/env bash
# Product-overridable app-eval runner. Same override pattern as run-tests.sh.
set -euo pipefail
THIS="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || realpath "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
ROOT="$(pwd)"
PRODUCT_RUNNER="${ROOT}/scripts/run-app-eval.sh"
if [[ -x "$PRODUCT_RUNNER" ]]; then
  PROD_REAL="$(readlink -f "$PRODUCT_RUNNER" 2>/dev/null || realpath "$PRODUCT_RUNNER" 2>/dev/null || echo "$PRODUCT_RUNNER")"
  if [[ "$PROD_REAL" != "$THIS" ]]; then
    exec "$PRODUCT_RUNNER" "$@"
  fi
fi
echo "no product app-eval runner; override scripts/run-app-eval.sh"
exit 0
