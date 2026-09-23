#!/usr/bin/env python3
"""Minimal YAML frontmatter helpers for L0 gates. stdlib only + optional PyYAML.

Prefer PyYAML if installed; otherwise a tiny subset parser for ticket fields.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1].strip("\n"), parts[2].lstrip("\n")


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')) and len(raw) >= 2:
        return raw[1:-1]
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw in ("null", "Null", "~"):
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    # bare words / paths
    return raw


def _parse_simple_yaml(fm: str) -> dict[str, Any]:
    """Parse a constrained subset used by tickets (keys, scalars, lists)."""
    data: dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    key_re = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = key_re.match(line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2)
        # inline comment strip for scalars
        if "#" in rest and not rest.strip().startswith("["):
            # keep quoted strings intact
            if not (rest.strip().startswith(("'", '"'))):
                rest = rest.split("#", 1)[0].rstrip()
        rest = rest.strip()
        if rest == "" or rest == "|":
            # possibly a list follows
            items: list[Any] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip() or nxt.strip().startswith("#"):
                    j += 1
                    continue
                if nxt.startswith("  - ") or nxt.startswith("- "):
                    item = nxt.lstrip()[2:].strip()
                    if "#" in item and not item.startswith(("'", '"')):
                        item = item.split("#", 1)[0].rstrip()
                    items.append(_parse_scalar(item))
                    j += 1
                    continue
                if key_re.match(nxt) and not nxt.startswith(" "):
                    break
                if nxt.startswith(" ") and not nxt.strip().startswith("-"):
                    # multiline scalar continuation — ignore for our fields
                    j += 1
                    continue
                break
            data[key] = items
            i = j
            continue
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                # try python-literal list of strings
                try:
                    data[key] = ast.literal_eval(rest)
                except Exception:
                    data[key] = [_parse_scalar(x.strip()) for x in inner.split(",") if x.strip()]
            i += 1
            continue
        data[key] = _parse_scalar(rest)
        i += 1
    return data


def load_frontmatter(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    fm, _ = split_frontmatter(text)
    if not fm:
        return {}
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(fm)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return _parse_simple_yaml(fm)


def find_ticket_file(ticket_id: str, roots: list[Path] | None = None) -> Path | None:
    """Find tickets/<id>*.md under product tickets/ or examples/*/tickets/."""
    cwd = Path.cwd()
    search_roots: list[Path] = []
    if roots:
        search_roots = roots
    else:
        for candidate in [
            cwd / "tickets",
            cwd / "examples",
        ]:
            if candidate.is_dir():
                search_roots.append(candidate)
        # also when cwd is kit root and examples has nested tickets
        # and when product has .sdlc — tickets at product root already covered
    matches: list[Path] = []
    for root in search_roots:
        if root.name == "tickets":
            for p in root.glob("*.md"):
                if ticket_id in p.name:
                    matches.append(p)
        else:
            for p in root.rglob("tickets/*.md"):
                if ticket_id in p.name:
                    matches.append(p)
    if not matches:
        # last resort: find anywhere under cwd excluding .git
        for p in cwd.rglob("*.md"):
            if ".git" in p.parts:
                continue
            if "tickets" in p.parts and ticket_id in p.name:
                matches.append(p)
    if not matches:
        return None
    # prefer exact prefix match T-042-03-...
    exact = [p for p in matches if p.name.startswith(ticket_id)]
    chosen = exact[0] if exact else matches[0]
    return chosen


def resolve_contracts_path(start: Path | None = None) -> Path | None:
    """Prefer product arch/CONTRACTS.md; fall back to nearest examples/*/arch/CONTRACTS.md."""
    cwd = Path.cwd() if start is None else start
    direct = cwd / "arch" / "CONTRACTS.md"
    if direct.is_file():
        return direct
    examples = cwd / "examples"
    if examples.is_dir():
        found = sorted(examples.glob("*/arch/CONTRACTS.md"))
        if found:
            return found[0]
    # walking up from a ticket path
    return None


if __name__ == "__main__":
    # CLI: frontmatter.py load <path> | find <id>
    if len(sys.argv) < 3:
        print("usage: frontmatter.py load <path> | find <id>", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "load":
        import json

        print(json.dumps(load_frontmatter(sys.argv[2]), indent=2))
    elif cmd == "find":
        p = find_ticket_file(sys.argv[2])
        if not p:
            sys.exit(1)
        print(p)
    else:
        sys.exit(2)
