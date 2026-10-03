"""Known failures a product adopted the kit with (sdlc-baseline.json), so a red base branch
does not block every ticket. A gate fails only on failures the baseline does not list; the
baseline may only shrink (`immutable`), and `gate ci` asks for entries that stopped failing
to be pruned. `sdlc trace` reads it too: shipped tickets adopted without proof are known
trace problems, not a red CI forever. Process checks (scope, immutable, review-file, skills,
ac-red) are never baselined: they judge the change itself, not the code it starts from."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# Checks whose failures describe the code base, so a known one may be carried.
BASELINE_CHECKS = ("artifacts", "contracts", "lint", "typecheck", "unit", "integration", "e2e",
                   "ac-coverage", "test-quality", "duplication", "build", "smoke", "trace")

# tsc: src/a.ts(12,3): error TS2345: ...
_TSC = re.compile(r"^(?P<file>[^\s(][^(]*)\(\d+,\d+\): error (?P<code>TS\d+)")
# mypy: src/a.py:12: error: ...  [arg-type]
_MYPY = re.compile(r"^(?P<file>[^\s:]+\.pyi?):\d+(?::\d+)?: error: .*\[(?P<code>[\w-]+)\]\s*$")
# ruff: src/a.py:12:3: F401 ...
_RUFF = re.compile(r"^(?P<file>[^\s:]+):\d+:\d+: (?P<code>[A-Z]+\d+)\b")
# eslint stylish: a path line, then "  12:3  error  message  rule-name"
_ESLINT_ROW = re.compile(r"^\s+\d+:\d+\s+error\s+.*?\s{2,}(?P<rule>[\w@/-]+)\s*$")
_LINE_NO = re.compile(r":\d+(?::\d+)?(?=[:;,\s]|$)")


def path(root: Path, cfg_paths: dict) -> Path:
    return root / cfg_paths.get("baseline", "sdlc-baseline.json")


def parse(text: str | None) -> dict[str, list[str]]:
    if not text:
        return {}
    data = json.loads(text)
    checks = data.get("checks", {}) if isinstance(data, dict) else {}
    return {k: [str(x) for x in v] for k, v in checks.items() if k in BASELINE_CHECKS and isinstance(v, list)}


def dump(checks: dict[str, list[str]]) -> str:
    body = {k: sorted(v) for k, v in sorted(checks.items()) if v}
    return json.dumps({"version": 1, "checks": body}, indent=2) + "\n"


def whole(name: str) -> str:
    """The key for a failing check whose output names no individual failure."""
    return f"{name}: fails"


def tool_findings(log_text: str) -> list[str]:
    """Stable keys from type checker / linter output: `file: code`, without line numbers,
    so an edit elsewhere in a file does not turn a known error into a new one."""
    out, eslint_file = [], None
    for line in log_text.splitlines():
        if m := (_TSC.match(line) or _MYPY.match(line) or _RUFF.match(line)):
            out.append(f"{m.group('file').strip()}: {m.group('code')}")
        elif m := _ESLINT_ROW.match(line):
            if eslint_file:
                out.append(f"{eslint_file}: {m.group('rule')}")
        elif line and not line[0].isspace() and not line.startswith("$") and "/" in line and " " not in line.strip():
            eslint_file = line.strip()
    return out


def detail_findings(details: list[str]) -> list[str]:
    """Detail lines as stable keys: line numbers removed, ERROR rows only for artifacts."""
    out = []
    for d in details:
        d = d.strip()
        if not d or d.startswith(("WARN", "note", "$")):
            continue
        out.append(_LINE_NO.sub("", d))
    return out


def compare(known: list[str], now: list[str]) -> tuple[list[str], list[str]]:
    """(new: failing now and not known, stale: known and no longer failing), as multisets."""
    k, n = Counter(known), Counter(now)
    return sorted((n - k).elements()), sorted((k - n).elements())


def grown(base: dict[str, list[str]], branch: dict[str, list[str]]) -> list[str]:
    """Entries the branch's baseline adds over the base branch's (it may only shrink)."""
    out = []
    for name, entries in branch.items():
        new, _ = compare(base.get(name, []), entries)
        out += [f"{name}: {e}" for e in new]
    return out
