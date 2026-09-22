#!/usr/bin/env bash
# Run from the PRODUCT repo root after .sdlc/ exists.
set -euo pipefail
root="$(pwd)"
kit="${root}/.sdlc"

if [[ ! -d "${kit}" || ! -f "${kit}/AGENTS.md" ]]; then
  echo "missing .sdlc/AGENTS.md — add the kit first (see .sdlc/CONSUME.md or the kit CONSUME.md)" >&2
  exit 1
fi

if [[ ! -f "${root}/AGENTS.md" ]]; then
  cp "${kit}/templates/product-AGENTS.md" "${root}/AGENTS.md"
  echo "wrote AGENTS.md shim"
else
  echo "keep existing AGENTS.md"
fi

mkdir -p "${root}/adapters" "${root}/skills/vendor" \
  "${root}/intent" "${root}/design/pages" "${root}/arch" \
  "${root}/decisions" "${root}/tickets" "${root}/reviews" "${root}/ops"

if [[ ! -f "${root}/adapters/MODELS.md" ]]; then
  cp "${kit}/adapters/MODELS.md" "${root}/adapters/MODELS.md"
  echo "wrote adapters/MODELS.md — fill L1/L2/L3"
fi

for s in frontend-patterns backend-patterns; do
  if [[ ! -d "${root}/skills/${s}" ]]; then
    cp -R "${kit}/skills/${s}" "${root}/skills/${s}"
    echo "copied skills/${s} — fill the Lock section in the first /architect"
  fi
done

if [[ ! -f "${root}/skills/VENDOR.lock.md" ]]; then
  cp "${kit}/skills/VENDOR.lock.md" "${root}/skills/VENDOR.lock.md"
fi

if [[ ! -f "${root}/tickets/TEMPLATE.md" ]]; then
  cp "${kit}/templates/ticket.md" "${root}/tickets/TEMPLATE.md"
fi

echo
echo "bootstrap ok."
echo "next: fill adapters/MODELS.md, bind the agent to ./AGENTS.md, first /intent."
echo "do not commit product secrets. do not edit .sdlc/ in feature PRs."
