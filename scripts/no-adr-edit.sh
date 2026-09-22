#!/usr/bin/env bash
# L0: fail if an existing decisions/ADR-*.md is modified. Adding a new ADR-NNNN is OK.
# Usage:
#   ./scripts/no-adr-edit.sh [paths…]
#   git diff --name-only | ./scripts/no-adr-edit.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

mapfile -t PATHS < <(collect_paths "$@")

if [[ ${#PATHS[@]} -eq 0 ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t PATHS < <(
    { git diff --name-only HEAD 2>/dev/null
      git diff --cached --name-only 2>/dev/null
      git ls-files -m 2>/dev/null
    } | awk '/decisions\/ADR-.*\.md$/' | awk 'NF && !seen[$0]++'
  )
fi

fail=0
for p in "${PATHS[@]+"${PATHS[@]}"}"; do
  [[ -z "$p" ]] && continue
  p="${p#./}"
  base="$(basename "$p")"
  case "$base" in
    ADR-*.md) ;;
    *) continue ;;
  esac

  in_head=0
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if git cat-file -e "HEAD:${p}" 2>/dev/null; then
      in_head=1
    fi
  elif [[ -f "$p" ]]; then
    # no git: treat existing file as "already present"
    in_head=1
  fi

  if [[ $in_head -eq 1 ]]; then
    echo "no-adr-edit: FAIL — existing ADR modified: $p (add ADR-N+1 instead)" >&2
    fail=1
  else
    echo "no-adr-edit: new ADR OK: $p"
  fi
done

if [[ $fail -ne 0 ]]; then
  exit 1
fi
echo "no-adr-edit: OK"
