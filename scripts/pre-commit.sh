#!/usr/bin/env bash
# Thin pre-commit wrapper. Products symlink:
#   ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit
#
# If TICKET_FILE or TICKET_ID is set, run verify-ticket + ticket-files on staged files.
# Always run no-adr-edit when decisions/ is staged.
set -euo pipefail

# Resolve kit scripts dir whether we are .sdlc/scripts or kit scripts/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_SCRIPTS="$SCRIPT_DIR"

# When installed as product hook via symlink to .sdlc/scripts/pre-commit.sh,
# repo root is cwd (git runs hooks from repo root).
ROOT="$(pwd)"

mapfile -t STAGED < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)

if [[ -n "${TICKET_FILE:-${TICKET_ID:-${TICKET:-}}}" ]]; then
  id_or_file="${TICKET_ID:-}"
  if [[ -n "${TICKET_FILE:-${TICKET:-}}" ]]; then
    export TICKET_FILE="${TICKET_FILE:-$TICKET}"
    "${KIT_SCRIPTS}/verify-ticket.sh" "$(basename "${TICKET_FILE}" | sed -E 's/^(T-[0-9]+-[0-9]+).*/\1/')"
  else
    "${KIT_SCRIPTS}/verify-ticket.sh" "$id_or_file"
  fi
  printf '%s\n' "${STAGED[@]+"${STAGED[@]}"}" | "${KIT_SCRIPTS}/ticket-files.sh" ${TICKET_ID:+--ticket "$TICKET_ID"}
fi

# Always gate ADR edits when decisions/ staged
adr_staged=0
for p in "${STAGED[@]+"${STAGED[@]}"}"; do
  case "$p" in
    decisions/ADR-*.md|*/decisions/ADR-*.md) adr_staged=1; break ;;
  esac
done
if [[ $adr_staged -eq 1 ]]; then
  printf '%s\n' "${STAGED[@]+"${STAGED[@]}"}" | "${KIT_SCRIPTS}/no-adr-edit.sh"
fi

exit 0
