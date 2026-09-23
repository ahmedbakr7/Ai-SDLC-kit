#!/usr/bin/env bash
# L0: new public seams in the diff must appear as text in arch/CONTRACTS.md.
# Heuristic (documented): prefer false positives over silent misses.
#
# Detects additions (lines starting with + in a unified diff, or whole-file scan)
# that look like:
#   - HTTP routes: app.get/post/…('/path'), @Get('path'), route('/path'),
#     fetch('/v1/…'), path strings matching /v[0-9]/…
#   - Exported event names: emit('event.name'), EVENT_ = '…', "domain.event"
#   - New tables/migrations: createTable('…'), CREATE TABLE …, migrations/*.sql names
#
# Usage:
#   ./scripts/no-contract-drift.sh [files…]
#   git diff HEAD | ./scripts/no-contract-drift.sh
#   ./scripts/no-contract-drift.sh --allow   # skip when only docs changed
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

ALLOW_DOCS=0
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow) ALLOW_DOCS=1; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

# Find CONTRACTS.md
CONTRACTS=""
if [[ -f arch/CONTRACTS.md ]]; then
  CONTRACTS="arch/CONTRACTS.md"
elif [[ -f examples/slice-042-return-status/arch/CONTRACTS.md ]]; then
  CONTRACTS="examples/slice-042-return-status/arch/CONTRACTS.md"
else
  CONTRACTS="$(python3 - <<'PY'
from pathlib import Path
cwd = Path.cwd()
direct = cwd / "arch" / "CONTRACTS.md"
if direct.is_file():
    print(direct)
else:
    found = sorted((cwd / "examples").glob("*/arch/CONTRACTS.md")) if (cwd / "examples").is_dir() else []
    print(found[0] if found else "")
PY
)"
fi
[[ -n "$CONTRACTS" && -f "$CONTRACTS" ]] || die "no-contract-drift: arch/CONTRACTS.md not found"

CONTRACTS_TEXT="$(cat "$CONTRACTS")"

mapfile -t PATHS < <(collect_paths "${ARGS[@]+"${ARGS[@]}"}")

# If only markdown/docs and --allow, pass
if [[ $ALLOW_DOCS -eq 1 && ${#PATHS[@]} -gt 0 ]]; then
  only_docs=1
  for p in "${PATHS[@]}"; do
    case "$p" in
      *.md|*.mdx|docs/*|*.txt|LICENSE*|README*) ;;
      *) only_docs=0; break ;;
    esac
  done
  if [[ $only_docs -eq 1 ]]; then
    echo "no-contract-drift: --allow and only docs; OK"
    exit 0
  fi
fi

# Build a "added lines" corpus: prefer git diff of given paths, else stdin, else cat files
ADDED="$(mktemp)"
trap 'rm -f "$ADDED"' EXIT

if [[ ${#PATHS[@]} -gt 0 ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # staged + unstaged unified diff for those paths; extract + lines
  git diff HEAD -- "${PATHS[@]}" 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' >"$ADDED" || true
  if [[ ! -s "$ADDED" ]]; then
    git diff --cached -- "${PATHS[@]}" 2>/dev/null | grep -E '^\+' | grep -v '^\+\+\+' >"$ADDED" || true
  fi
  if [[ ! -s "$ADDED" ]]; then
    # no git diff — scan file contents as "new"
    for p in "${PATHS[@]}"; do
      [[ -f "$p" ]] && sed 's/^/+/' "$p" >>"$ADDED"
    done
  fi
elif [[ ! -t 0 ]]; then
  grep -E '^\+' | grep -v '^\+\+\+' >"$ADDED" || true
elif [[ ${#PATHS[@]} -gt 0 ]]; then
  for p in "${PATHS[@]}"; do
    [[ -f "$p" ]] && sed 's/^/+/' "$p" >>"$ADDED"
  done
else
  echo "no-contract-drift: no paths or diff; OK"
  exit 0
fi

python3 - "$ADDED" "$CONTRACTS" <<'PY'
import re, sys
from pathlib import Path

added = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
contracts = Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace")

# Collect candidate symbols from added lines
candidates: set[str] = set()

# HTTP-ish path literals
for m in re.finditer(r"""['"`](/v\d+/[A-Za-z0-9_{\}-]+(?:/[A-Za-z0-9_{\}-]+)*)['"`]""", added):
    candidates.add(m.group(1))
for m in re.finditer(r"""(?:app|router|route)\.(?:get|post|put|patch|delete|options|head)\(\s*['"`]([^'"`]+)['"`]""", added, re.I):
    candidates.add(m.group(1))
for m in re.finditer(r"""@(?:Get|Post|Put|Patch|Delete)\(\s*['"`]([^'"`]+)['"`]""", added):
    candidates.add(m.group(1))

# Event names: emit('x.y'), EVENT_FOO = 'x.y'
for m in re.finditer(r"""(?:emit|publish|dispatch)\(\s*['"`]([A-Za-z][\w.-]+)['"`]""", added):
    candidates.add(m.group(1))
for m in re.finditer(r"""\b(?:EVENT|eventName|EVENT_NAME)\s*[:=]\s*['"`]([A-Za-z][\w.-]+)['"`]""", added):
    candidates.add(m.group(1))

# Tables / migrations
for m in re.finditer(r"""createTable\(\s*['"`]([A-Za-z_][\w]*)['"`]""", added):
    candidates.add(m.group(1))
for m in re.finditer(r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"]?([A-Za-z_][\w]*)""", added, re.I):
    candidates.add(m.group(1))

# Filter noise
noise = {"/", "/api", "/health", "/ready", "id", "string", "number"}
candidates = {c for c in candidates if c not in noise and len(c) > 1}

missing = sorted(c for c in candidates if c not in contracts)
if missing:
    print("no-contract-drift: FAIL — new symbols not found in CONTRACTS.md:", file=sys.stderr)
    for c in missing:
        print(f"  {c}", file=sys.stderr)
    print(f"(contracts file: {sys.argv[2]})", file=sys.stderr)
    print("Heuristic: false positives > silent misses. Use --allow only for docs-only commits.", file=sys.stderr)
    sys.exit(1)
print(f"no-contract-drift: OK (scanned {len(candidates)} candidate symbol(s))")
PY
