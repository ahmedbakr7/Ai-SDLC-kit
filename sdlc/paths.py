"""One glob dialect for every check, independent of Python version.

    **/   zero or more directories      *   any chars except '/'
    **    anything (including '/')      ?   one char except '/'
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def match(path: str, pattern: str) -> bool:
    if pattern.startswith("./"):
        pattern = pattern[2:]
    return bool(_compile(pattern).match(path))


def match_any(path: str, patterns: list[str]) -> bool:
    return any(match(path, p) for p in patterns)


def repo_files(root: Path) -> list[str]:
    """Tracked + untracked-but-not-ignored files (so node_modules, build output are skipped)."""
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.is_file() and not {".git", "node_modules"} & set(p.parts))
    return sorted({ln for ln in r.stdout.splitlines() if ln and (root / ln).is_file()})


def glob_files(root: Path, patterns: list[str], exclude: list[str] | None = None) -> list[str]:
    exclude = exclude or []
    return [f for f in repo_files(root) if match_any(f, patterns) and not match_any(f, exclude)]
