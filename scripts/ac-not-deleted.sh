#!/usr/bin/env bash
# L0: on ticket markdown diffs, fail if an acceptance_criteria item present in HEAD
# is absent in the working copy, unless commit message / trailer contains `spec:`
# pointing at a spec file that also changed.
#
# Usage:
#   ./scripts/ac-not-deleted.sh [ticket.md…]
#   GIT_COMMIT_MSG='spec: design/spec-042.md' ./scripts/ac-not-deleted.sh tickets/T-….md
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
require_python

mapfile -t PATHS < <(collect_paths "$@")
if [[ ${#PATHS[@]} -eq 0 ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t PATHS < <(
    { git diff --cached --name-only 2>/dev/null; git diff --name-only HEAD 2>/dev/null; } \
      | awk '/tickets\/.*\.md$/ || /\/tickets\/.*\.md$/' | awk 'NF && !seen[$0]++'
  )
fi

MSG="${GIT_COMMIT_MSG:-}"
if [[ -z "$MSG" ]]; then
  if [[ -f .git/COMMIT_EDITMSG ]]; then
    MSG="$(cat .git/COMMIT_EDITMSG)"
  elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    MSG="$(git log -1 --pretty=%B 2>/dev/null || true)"
  fi
fi

SPEC_PATH=""
if [[ "$MSG" =~ [Ss]pec:[[:space:]]*([^[:space:]]+) ]]; then
  SPEC_PATH="${BASH_REMATCH[1]}"
fi

spec_ok=0
if [[ -n "$SPEC_PATH" ]]; then
  mapfile -t ALL_CHANGED < <(
    { printf '%s\n' "${PATHS[@]+"${PATHS[@]}"}"
      git diff --name-only HEAD 2>/dev/null || true
      git diff --cached --name-only 2>/dev/null || true
    } | awk 'NF && !seen[$0]++'
  )
  for c in "${ALL_CHANGED[@]+"${ALL_CHANGED[@]}"}"; do
    if [[ "$c" == "$SPEC_PATH" || "$c" == */"$SPEC_PATH" || "$(basename "$c")" == "$(basename "$SPEC_PATH")" ]]; then
      spec_ok=1
      break
    fi
  done
  if [[ $spec_ok -eq 0 && -f "$SPEC_PATH" ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git diff --quiet HEAD -- "$SPEC_PATH" 2>/dev/null; then
      spec_ok=1
    fi
  fi
fi

fail=0
for p in "${PATHS[@]+"${PATHS[@]}"}"; do
  [[ -z "$p" ]] && continue
  case "$p" in
    tickets/*.md|*/tickets/*.md) ;;
    *) continue ;;
  esac
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
  git cat-file -e "HEAD:${p}" 2>/dev/null || continue

  if ! python3 - "$p" "$spec_ok" "$SCRIPT_DIR" <<'PY'
import subprocess, sys
from pathlib import Path

path, spec_ok, script_dir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, f"{script_dir}/lib")
from frontmatter import split_frontmatter, _parse_simple_yaml

def ac_items(text: str):
    fm, _ = split_frontmatter(text)
    if not fm:
        return []
    try:
        import yaml
        d = yaml.safe_load(fm) or {}
    except Exception:
        d = _parse_simple_yaml(fm)
    if not isinstance(d, dict):
        return []
    ac = d.get("acceptance_criteria") or []
    if not isinstance(ac, list):
        ac = [ac]
    return [str(x).strip() for x in ac if str(x).strip()]

head = subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True, errors="replace")
work = Path(path).read_text(encoding="utf-8")
old = set(ac_items(head))
new = set(ac_items(work))
missing = sorted(old - new)
if missing and not spec_ok:
    print(f"ac-not-deleted: FAIL — acceptance_criteria removed from {path}:", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    print("Allow only with commit trailer `spec: <path>` and that spec file also changed.", file=sys.stderr)
    sys.exit(1)
if missing and spec_ok:
    print(f"ac-not-deleted: AC removed from {path} but spec: trailer OK")
sys.exit(0)
PY
  then
    fail=1
  fi
done

if [[ $fail -ne 0 ]]; then
  exit 1
fi
echo "ac-not-deleted: OK"
