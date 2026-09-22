#!/usr/bin/env bash
# Product-overridable test runner.
# If product scripts/run-tests.sh exists and is not this file, exec it.
# Else try package.json / pyproject.toml / Makefile test target.
# Else exit 0 with a message.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIS="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || realpath "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"

# Prefer product override at repo root when kit is at .sdlc/scripts/
ROOT="$(pwd)"
PRODUCT_RUNNER="${ROOT}/scripts/run-tests.sh"
if [[ -x "$PRODUCT_RUNNER" ]]; then
  PROD_REAL="$(readlink -f "$PRODUCT_RUNNER" 2>/dev/null || realpath "$PRODUCT_RUNNER" 2>/dev/null || echo "$PRODUCT_RUNNER")"
  if [[ "$PROD_REAL" != "$THIS" ]]; then
    exec "$PRODUCT_RUNNER" "$@"
  fi
fi

if [[ -f "${ROOT}/package.json" ]] && command -v npm >/dev/null 2>&1; then
  if python3 -c "import json;s=json.load(open('package.json')).get('scripts') or {}; raise SystemExit(0 if 'test' in s else 1)" 2>/dev/null; then
    exec npm test "$@"
  fi
fi

if [[ -f "${ROOT}/pyproject.toml" ]]; then
  if command -v pytest >/dev/null 2>&1; then
    exec pytest "$@"
  fi
  if command -v python3 >/dev/null 2>&1; then
    if grep -q '\[tool.pytest' pyproject.toml 2>/dev/null || grep -q pytest pyproject.toml 2>/dev/null; then
      exec python3 -m pytest "$@"
    fi
  fi
fi

if [[ -f "${ROOT}/Makefile" ]] && grep -qE '^test:' Makefile; then
  exec make test
fi

echo "no product test runner; override scripts/run-tests.sh"
exit 0
