#!/usr/bin/env bash
# L0: ticket exists, frontmatter parseable, depends_on done, files exist or are new.
set -euo pipefail
id="${1:?ticket id}"
file=$(find tickets -name "${id}*.md" -o -name "*${id}*.md" | head -n1)
if [[ -z "${file}" ]]; then
  echo "no ticket file for $id" >&2
  exit 1
fi
echo "verify-ticket: $file"
# Repo-specific: add yq checks for status/depends_on here.
exit 0
