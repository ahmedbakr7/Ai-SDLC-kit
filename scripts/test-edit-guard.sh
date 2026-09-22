#!/usr/bin/env bash
# L0: for play=build, fail if test files change and no production file in ticket
# files: also changes. For play=test: skip/pass.
#
# Usage:
#   PLAY=build ./scripts/test-edit-guard.sh --ticket T-042-03 [paths…]
#   TICKET=tickets/T-….md ./scripts/test-edit-guard.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

resolve_ticket "$@"
PLAY="$(play_from_ticket_or_env)"

if [[ "$PLAY" == "test" ]]; then
  echo "test-edit-guard: play=test; skip OK"
  exit 0
fi

[[ -n "${TICKET_FILE:-}" ]] || die "test-edit-guard: need --ticket / TICKET= for play=build"

mapfile -t PATHS < <(collect_paths "${RESOLVED_ARGS[@]+"${RESOLVED_ARGS[@]}"}")
if [[ ${#PATHS[@]} -eq 0 ]]; then
  echo "test-edit-guard: no paths; OK"
  exit 0
fi

mapfile -t LISTED < <(python3 - <<PY
import sys
sys.path.insert(0, "${SCRIPT_DIR}/lib")
from frontmatter import load_frontmatter
fm = load_frontmatter("${TICKET_FILE}")
for f in (fm.get("files") or []):
    if f:
        print(f)
PY
)

has_test=0
has_prod=0
for p in "${PATHS[@]}"; do
  p="${p#./}"
  if is_test_path "$p"; then
    has_test=1
    continue
  fi
  for f in "${LISTED[@]+"${LISTED[@]}"}"; do
    if [[ "$p" == "$f" ]]; then
      has_prod=1
      break
    fi
  done
done

if [[ $has_test -eq 1 && $has_prod -eq 0 ]]; then
  echo "test-edit-guard: FAIL — test files changed with no production file from ticket files: in the same change set (play=build)" >&2
  exit 1
fi
echo "test-edit-guard: OK"
