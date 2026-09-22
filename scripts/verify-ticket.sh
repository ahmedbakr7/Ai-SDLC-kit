#!/usr/bin/env bash
# L0: ticket exists, required frontmatter fields present, depends_on resolve.
# Usage: ./scripts/verify-ticket.sh <ticket-id>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
require_python

id="${1:?usage: verify-ticket.sh <ticket-id>}"
TICKET_FILE="$(python3 "${SCRIPT_DIR}/lib/frontmatter.py" find "$id")" \
  || die "no ticket file for $id"

python3 - "$TICKET_FILE" "$id" "$SCRIPT_DIR" <<'PY'
import sys
from pathlib import Path

path, want_id, script_dir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, f"{script_dir}/lib")
from frontmatter import load_frontmatter, find_ticket_file

fm = load_frontmatter(path)
required = [
    "id", "title", "type", "status", "depends_on", "files", "skills", "acceptance_criteria"
]
missing = [k for k in required if k not in fm]
if missing:
    print(f"verify-ticket: FAIL — missing fields {missing} in {path}", file=sys.stderr)
    sys.exit(1)

status = fm.get("status")
if status is None or (isinstance(status, str) and not status.strip()):
    print(f"verify-ticket: FAIL — empty status in {path}", file=sys.stderr)
    sys.exit(1)

tid = str(fm.get("id", ""))
if want_id not in tid and tid not in want_id:
    # allow find by prefix; still require id present
    pass

deps = fm.get("depends_on") or []
if not isinstance(deps, list):
    deps = [deps]
for dep in deps:
    dep = str(dep).strip()
    if not dep:
        continue
    found = find_ticket_file(dep)
    if not found:
        print(f"verify-ticket: FAIL — depends_on '{dep}' has no matching file under tickets/ (or examples/*/tickets/)", file=sys.stderr)
        sys.exit(1)

print(f"verify-ticket: {path}")
print("OK")
PY
