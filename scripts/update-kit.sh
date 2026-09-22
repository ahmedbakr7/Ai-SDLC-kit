#!/usr/bin/env bash
# Bump .sdlc in a product repo. Run from product root.
set -euo pipefail
root="$(pwd)"
ref="${1:-}"

if [[ ! -d "${root}/.sdlc" ]]; then
  echo "no .sdlc directory" >&2
  exit 1
fi

if [[ -f "${root}/.gitmodules" ]] && grep -q '[.]sdlc' "${root}/.gitmodules" 2>/dev/null; then
  git submodule update --init --recursive .sdlc
  git -C .sdlc fetch --tags origin
  if [[ -n "${ref}" ]]; then
    git -C .sdlc checkout "${ref}"
  else
    git -C .sdlc checkout main
    git -C .sdlc pull --ff-only origin main
  fi
  echo "submodule .sdlc now at $(git -C .sdlc rev-parse --short HEAD)"
  echo "commit the gitlink: git add .sdlc && git commit -m \"bump ai-sdlc-kit\""
else
  echo "subtree detected (or no submodule). pull manually:"
  echo "  git subtree pull --prefix .sdlc <KIT-REMOTE> ${ref:-main} --squash"
fi
