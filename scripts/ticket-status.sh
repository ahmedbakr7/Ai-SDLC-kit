#!/usr/bin/env bash
# L0: fail if ticket status is not in_review or done when --require-review-status is set.
# Usage:
#   ./scripts/ticket-status.sh --ticket T-042-03 --require-review-status
#   ./scripts/ticket-status.sh T-042-03
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REQUIRE_REVIEW_STATUS=0
resolve_ticket "$@"
[[ -n "${TICKET_FILE:-}" ]] || die "ticket-status: need --ticket / TICKET= / id"

status="$(python3 - <<PY
import sys
sys.path.insert(0, "${SCRIPT_DIR}/lib")
from frontmatter import load_frontmatter
fm = load_frontmatter("${TICKET_FILE}")
print(fm.get("status") or "")
PY
)"

if [[ -z "$status" ]]; then
  echo "ticket-status: FAIL — empty status in ${TICKET_FILE}" >&2
  exit 1
fi

if [[ "${REQUIRE_REVIEW_STATUS:-0}" -eq 1 ]]; then
  case "$status" in
    in_review|done) ;;
    *)
      echo "ticket-status: FAIL — status='$status' (need in_review or done) in ${TICKET_FILE}" >&2
      exit 1
      ;;
  esac
fi

echo "ticket-status: OK (${TICKET_FILE} status=$status)"
