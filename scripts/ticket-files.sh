#!/usr/bin/env bash
# L0: changed paths must be in ticket files: or allowed test paths.
# Usage:
#   TICKET=tickets/T-….md ./scripts/ticket-files.sh [paths…]
#   ./scripts/ticket-files.sh --ticket T-042-03 [paths…]
#   git diff --cached --name-only | ./scripts/ticket-files.sh --ticket T-042-03
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

resolve_ticket "$@"
[[ -n "${TICKET_FILE:-}" ]] || die "ticket-files: set TICKET=path, TICKET_FILE=, or --ticket <id>"

mapfile -t PATHS < <(collect_paths "${RESOLVED_ARGS[@]+"${RESOLVED_ARGS[@]}"}")
if [[ ${#PATHS[@]} -eq 0 ]]; then
  echo "ticket-files: no paths to check; OK"
  exit 0
fi

PLAY="$(play_from_ticket_or_env)"

# Load files: list from ticket
mapfile -t LISTED < <(python3 - <<PY
import sys
sys.path.insert(0, "${SCRIPT_DIR}/lib")
from frontmatter import load_frontmatter
fm = load_frontmatter("${TICKET_FILE}")
files = fm.get("files") or []
if not isinstance(files, list):
    files = [files]
for f in files:
    if f:
        print(f)
PY
)

declare -A ALLOWED=()
for f in "${LISTED[@]+"${LISTED[@]}"}"; do
  ALLOWED["$f"]=1
done

fail=0
for p in "${PATHS[@]}"; do
  # normalize leading ./
  p="${p#./}"
  if [[ -n "${ALLOWED[$p]+x}" ]]; then
    continue
  fi
  if is_test_path "$p"; then
    if [[ "$PLAY" == "test" ]]; then
      # play=test: any test/e2e/eval path allowed
      continue
    fi
    # play=build (default): only unit tests beside a listed production file
    if test_beside_listed "$p" "${LISTED[@]+"${LISTED[@]}"}"; then
      continue
    fi
    echo "ticket-files: FAIL $p — test path not beside any ticket files: entry (play=$PLAY)" >&2
    fail=1
    continue
  fi
  echo "ticket-files: FAIL $p — not in ticket files: of ${TICKET_FILE}" >&2
  fail=1
done

if [[ $fail -ne 0 ]]; then
  echo "ticket-files: allowed files:" >&2
  printf '  %s\n' "${LISTED[@]+"${LISTED[@]}"}" >&2
  exit 1
fi
echo "ticket-files: OK (${#PATHS[@]} path(s) vs ${TICKET_FILE})"
