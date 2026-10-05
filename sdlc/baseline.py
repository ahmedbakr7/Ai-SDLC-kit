"""Known failures a product adopted the kit with (sdlc-baseline.json), so a red base branch
does not block every ticket. A gate fails only on failures the baseline does not list; the
baseline may only shrink (`immutable`), and `gate ci` asks for entries that stopped failing
to be pruned. `sdlc trace` reads it too: shipped tickets adopted without proof are known
trace problems, not a red CI forever. Process checks (scope, immutable, review-file, skills,
ac-red) are never baselined: they judge the change itself, not the code it starts from.

Version 2 (ADR-0002) stores a count per key. Paths inside keys follow the renames git detects
since the baseline was written, so moving a file keeps its known failures known."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from . import gitutil

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
# A key's count above MAX_COUNT is not a count a run produces: it carries nothing. Past MAX_TOTAL
# occurrences in the whole file, later keys carry nothing either. Either way a hand-edited file
# cannot make every gate expand it into memory, and the gate only gets stricter.
MAX_COUNT = 10_000
MAX_TOTAL = 1_000_000
# Characters a path is made of: a renamed path is replaced only where it stands whole.
_PATH_CHAR = r"[\w./@+~-]"


def path(root: Path, cfg_paths: dict) -> Path:
    return root / cfg_paths.get("baseline", "sdlc-baseline.json")


def parse(text: str | None) -> dict[str, list[str]]:
    """Known failures per check, as a multiset (a key repeats once per occurrence). Reads
    version 1 (a list of keys) and version 2 (`{key: count}`)."""
    if not text:
        return {}
    data = json.loads(text)
    checks = data.get("checks", {}) if isinstance(data, dict) else {}
    out: dict[str, list[str]] = {}
    total = 0
    for name, v in checks.items():
        if name not in BASELINE_CHECKS:
            continue
        if isinstance(v, list):
            v = Counter(map(str, v))
        if not isinstance(v, dict):
            continue
        keys: list[str] = []
        for k, n in v.items():
            # A count that is not an integer from 1 to MAX_COUNT carries nothing.
            if isinstance(n, int) and not isinstance(n, bool) and 0 < n <= MAX_COUNT and total + n <= MAX_TOTAL:
                keys += [str(k)] * n
                total += n
        out[name] = keys
    return out


def dump(checks: dict[str, list[str]]) -> str:
    """Version 2 text. Raises ValueError rather than write counts `parse` would not carry."""
    body = {k: dict(sorted(Counter(v).items())) for k, v in sorted(checks.items()) if v}
    counts = [n for entries in body.values() for n in entries.values()]
    if any(n > MAX_COUNT for n in counts) or sum(counts) > MAX_TOTAL:
        raise ValueError(f"more failures than a baseline carries ({MAX_COUNT} per key, {MAX_TOTAL} in all)")
    return json.dumps({"version": 2, "checks": body}, indent=2) + "\n"


def renames(root: Path, since: str, to: str = "HEAD") -> dict[str, str]:
    """Old path -> new path for the files git sees as renamed (exact or similar) from `since`
    to `to`. Empty when either commit is missing (a shallow clone): nothing is remapped."""
    out = gitutil.git(root, "diff", "-M", "--name-status", "-z", "--relative", since, to, check=False)
    fields, found = out.split("\0"), {}
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status.startswith(("R", "C")):
            if status.startswith("R") and i + 2 < len(fields):
                found[fields[i + 1]] = fields[i + 2]
            i += 3
        else:
            i += 2
    return found


def remap(checks: dict[str, list[str]], moved: dict[str, str]) -> dict[str, list[str]]:
    """Each key with every renamed path in it replaced by its new path, where the path stands
    whole (not inside a longer path). Keys without a path (test names, ticket ids) stay."""
    if not moved:
        return checks
    pat = re.compile(rf"(?<!{_PATH_CHAR})(?:{'|'.join(re.escape(o) for o in sorted(moved, key=len, reverse=True))})"
                     rf"(?!{_PATH_CHAR})")
    return {name: [pat.sub(lambda m: moved[m.group(0)], k) for k in keys] for name, keys in checks.items()}


def _written(root: Path, rel: str, rev: str = "HEAD") -> str:
    """The commit that last changed the baseline as `rev` has it ("" when none)."""
    return gitutil.git(root, "log", "-1", "--format=%H", rev, "--", rel, check=False).strip()


def load(root: Path, rel: str) -> dict[str, list[str]]:
    """The working tree's baseline, with paths moved since it was last committed renamed, also
    when it has uncommitted edits (a path already current is not an old path, so it stays)."""
    f = root / rel
    if not f.is_file():
        return {}
    text = f.read_text(encoding="utf-8")
    since = _written(root, rel)
    if not since:
        return parse(text)
    return remap(parse(text), renames(root, since))


def load_at(root: Path, rev: str, rel: str) -> dict[str, list[str]] | None:
    """The baseline as commit `rev` has it, with paths renamed up to HEAD (None: no file)."""
    text = gitutil.show(root, rev, "./" + rel)
    if text is None:
        return None
    since = _written(root, rel, rev)
    return remap(parse(text), renames(root, since)) if since else parse(text)


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
