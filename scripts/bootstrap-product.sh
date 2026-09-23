#!/usr/bin/env bash
# Run from the PRODUCT repo root after .sdlc/ exists.
# Usage: .sdlc/scripts/bootstrap-product.sh [--hooks]
set -euo pipefail
root="$(pwd)"
kit="${root}/.sdlc"
INSTALL_HOOKS=0
for arg in "$@"; do
  case "$arg" in
    --hooks) INSTALL_HOOKS=1 ;;
    -h|--help)
      echo "usage: bootstrap-product.sh [--hooks]"
      exit 0
      ;;
  esac
done

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
if [[ -d "${root}/.git" ]]; then
  hook_src="../../.sdlc/scripts/pre-commit.sh"
  hook_dst="${root}/.git/hooks/pre-commit"
  if [[ $INSTALL_HOOKS -eq 1 ]]; then
    mkdir -p "${root}/.git/hooks"
    ln -sf "$hook_src" "$hook_dst"
    echo "installed pre-commit hook -> $hook_src"
  else
    echo "pre-commit hook not installed (pass --hooks to install)."
    echo "one-liner:"
    echo "  ln -sf ../../.sdlc/scripts/pre-commit.sh .git/hooks/pre-commit"
  fi
else
  echo "no .git directory; skip hook install instructions."
fi

echo
echo "bootstrap ok."
echo "next: fill adapters/MODELS.md, bind the agent to ./AGENTS.md, walk .sdlc/examples/slice-042-return-status/, first /intent."
echo "do not commit product secrets. do not edit .sdlc/ in feature PRs."
