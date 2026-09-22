#!/usr/bin/env bash
# Kit-repo CI: referenced scripts/commands exist; SKILL.md frontmatter; scripts executable.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0

echo "== check-kit: referenced scripts/*.sh =="
# Grep markdown for scripts/*.sh references
while IFS= read -r ref; do
  [[ -z "$ref" ]] && continue
  # normalize
  rel="${ref#./}"
  if [[ ! -f "$ROOT/$rel" ]]; then
    echo "FAIL: markdown references missing $rel" >&2
    fail=1
  fi
done < <(
  grep -RhoE 'scripts/[A-Za-z0-9_./-]+\.sh' --include='*.md' . 2>/dev/null \
    | grep -v '^\.git' | sort -u
)

echo "== check-kit: referenced commands/*.md =="
while IFS= read -r ref; do
  [[ -z "$ref" ]] && continue
  rel="${ref#./}"
  # skip if it's a directory mention without file — still require file
  if [[ ! -f "$ROOT/$rel" ]]; then
    echo "FAIL: markdown references missing $rel" >&2
    fail=1
  fi
done < <(
  grep -RhoE 'commands/[A-Za-z0-9_./-]+\.md' --include='*.md' . 2>/dev/null \
    | sort -u
)

echo "== check-kit: skills/*/SKILL.md frontmatter =="
require_name_desc() {
  local f="$1"
  python3 - "$f" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
if not text.startswith("---"):
    print(f"FAIL: {sys.argv[1]} missing YAML frontmatter", file=sys.stderr)
    sys.exit(1)
parts = text.split("---", 2)
fm = parts[1]
folder = Path(sys.argv[1]).parent.name
has_name = False
has_desc = False
name_val = None
for line in fm.splitlines():
    if line.startswith("name:"):
        has_name = True
        name_val = line.split(":", 1)[1].strip().strip("\"'")
    if line.startswith("description:"):
        has_desc = True
if not has_name or not has_desc:
    print(f"FAIL: {sys.argv[1]} needs name: and description: in frontmatter", file=sys.stderr)
    sys.exit(1)
if name_val != folder:
    print(f"FAIL: {sys.argv[1]} name={name_val!r} != folder {folder!r}", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
PY
}

shopt -s nullglob
for skill in "$ROOT"/skills/*/SKILL.md; do
  # skip vendor README-only folders without SKILL — only SKILL.md paths
  dir="$(basename "$(dirname "$skill")")"
  if [[ "$dir" == "vendor" ]]; then
    continue
  fi
  if ! require_name_desc "$skill"; then
    fail=1
  fi
done

echo "== check-kit: scripts/*.sh executable =="
for s in "$ROOT"/scripts/*.sh; do
  if [[ ! -x "$s" ]]; then
    echo "FAIL: not executable: ${s#$ROOT/}" >&2
    fail=1
  fi
done

echo "== check-kit: verify example tickets =="
if [[ -d "$ROOT/examples" ]]; then
  while IFS= read -r tf; do
    id="$(basename "$tf" | sed -E 's/^(T-[0-9]+-[0-9]+).*/\1/')"
    if [[ -n "$id" ]]; then
      if ! "$ROOT/scripts/verify-ticket.sh" "$id"; then
        echo "FAIL: verify-ticket $id" >&2
        fail=1
      fi
    fi
  done < <(find "$ROOT/examples" -path '*/tickets/T-*.md' | sort)
fi

if [[ $fail -ne 0 ]]; then
  echo "check-kit: FAILED" >&2
  exit 1
fi
echo "check-kit: OK"
