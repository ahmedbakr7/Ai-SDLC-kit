#!/usr/bin/env bash
# Shared helpers for L0 scripts. Sourced by scripts/*.sh
# shellcheck disable=SC2034

_KIT_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_KIT_ROOT="$(cd "${_KIT_SCRIPTS_DIR}/.." && pwd)"
_FM_PY="${_KIT_SCRIPTS_DIR}/lib/frontmatter.py"

die() { echo "$*" >&2; exit 1; }

require_python() {
  command -v python3 >/dev/null 2>&1 || die "python3 required for YAML frontmatter parsing (see hooks/README.md)"
}

# Resolve ticket file from TICKET=path, --ticket ID, or first positional id.
# Sets: TICKET_FILE, TICKET_ID, PLAY (from env PLAY or ticket type heuristic / env)
resolve_ticket() {
  require_python
  local explicit="${TICKET_FILE:-${TICKET:-}}"
  local id="${TICKET_ID:-}"
  # parse args for --ticket
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ticket|-t)
        id="${2:?--ticket needs value}"
        shift 2
        ;;
      --play)
        PLAY="${2:?}"
        shift 2
        ;;
      --require-review-status)
        REQUIRE_REVIEW_STATUS=1
        shift
        ;;
      --allow)
        ALLOW_DOCS=1
        shift
        ;;
      --)
        shift
        args+=("$@")
        break
        ;;
      -*)
        die "unknown flag: $1"
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done
  RESOLVED_ARGS=("${args[@]}")

  if [[ -n "$explicit" ]]; then
    TICKET_FILE="$explicit"
  elif [[ -n "$id" ]]; then
    TICKET_FILE="$(python3 "${_FM_PY}" find "$id")" || die "no ticket file for $id"
  elif [[ ${#args[@]} -gt 0 && "${args[0]}" == T-* ]]; then
    id="${args[0]}"
    TICKET_FILE="$(python3 "${_FM_PY}" find "$id")" || die "no ticket file for $id"
    RESOLVED_ARGS=("${args[@]:1}")
  fi

  if [[ -n "${TICKET_FILE:-}" ]]; then
    [[ -f "$TICKET_FILE" ]] || die "ticket file not found: $TICKET_FILE"
    if [[ -z "${TICKET_ID:-}" ]]; then
      TICKET_ID="$(python3 -c "import sys; sys.path.insert(0,'${_KIT_SCRIPTS_DIR}/lib'); from frontmatter import load_frontmatter; print(load_frontmatter(sys.argv[1]).get('id',''))" "$TICKET_FILE")"
    fi
  fi
}

# Read changed paths from args or stdin (one per line). Dedup.
collect_paths() {
  local -a out=()
  if [[ $# -gt 0 ]]; then
    out=("$@")
  elif [[ ! -t 0 ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ -z "$line" ]] && continue
      out+=("$line")
    done
  fi
  if [[ ${#out[@]} -eq 0 ]]; then
    # default: staged files if in a git repo
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      mapfile -t out < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
    fi
  fi
  printf '%s\n' "${out[@]}" | awk 'NF && !seen[$0]++'
}

is_test_path() {
  local p="$1"
  case "$p" in
    e2e/*|*/e2e/*|evals/*|*/evals/*) return 0 ;;
  esac
  [[ "$p" == *".test."* || "$p" == *".spec."* ]] && return 0
  [[ "$p" == *_test.py || "$p" == */test_*.py || "$p" == */*_test.go ]] && return 0
  return 1
}

# True if test path sits beside a listed production file (same dir, stem match soft).
test_beside_listed() {
  local test_path="$1"
  shift
  local listed=("$@")
  local tdir tbase
  tdir="$(dirname "$test_path")"
  tbase="$(basename "$test_path")"
  # strip common test suffixes for stem compare
  local stem="$tbase"
  stem="${stem%.ts}"; stem="${stem%.tsx}"; stem="${stem%.js}"; stem="${stem%.jsx}"
  stem="${stem%.py}"; stem="${stem%.go}"
  stem="${stem%.test}"; stem="${stem%.spec}"
  stem="${stem%_test}"; stem="${stem#test_}"
  local f fdir fbase fstem
  for f in "${listed[@]}"; do
    fdir="$(dirname "$f")"
    [[ "$tdir" == "$fdir" ]] || continue
    fbase="$(basename "$f")"
    fstem="${fbase%.*}"
    if [[ "$stem" == "$fstem"* || "$fstem" == "$stem"* || "$tdir" == "$fdir" ]]; then
      # same directory as a listed production file is enough for unit-test-beside rule
      return 0
    fi
  done
  return 1
}

play_from_ticket_or_env() {
  if [[ -n "${PLAY:-}" ]]; then
    echo "$PLAY"
    return
  fi
  if [[ -n "${TICKET_FILE:-}" ]]; then
    local t
    t="$(python3 -c "import sys; sys.path.insert(0,'${_KIT_SCRIPTS_DIR}/lib'); from frontmatter import load_frontmatter; print(load_frontmatter(sys.argv[1]).get('type',''))" "$TICKET_FILE" 2>/dev/null || true)"
    if [[ "$t" == "test" ]]; then
      echo "test"
      return
    fi
  fi
  echo "build"
}
