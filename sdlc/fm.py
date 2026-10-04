"""Strict frontmatter parser for kit artifacts.

Artifacts use a documented YAML *subset* so every tool parses them the same way,
with no optional dependency changing the result:

    key: scalar              # bare, "double" or 'single' quoted, true/false/null, int
    key: [a, "b c", 3]       # inline list of scalars
    key:                     # block list of scalars
      - a
      - "b: c"
    key: |                   # literal block (newlines kept); '>' folds to spaces
      text

Anything else (nested maps, anchors, flow maps) is a ParseError with a line number.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s+(.*)|\s*)$")
INT_RE = re.compile(r"^-?(?:0|[1-9]\d*)$")  # a leading zero keeps the text: 0510682 is a commit


class ParseError(ValueError):
    def __init__(self, path: str, line: int, msg: str):
        super().__init__(f"{path}:{line}: {msg}")
        self.path, self.line, self.msg = path, line, msg


def split(text: str) -> tuple[str | None, str, int]:
    """Return (frontmatter, body, body_start_line). frontmatter is None if absent."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, 1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]), i + 2
    return None, text, 1


def _strip_comment(raw: str) -> str:
    # A comment starts at ' #' outside quotes.
    out, quote = [], None
    for i, ch in enumerate(raw):
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"':
                continue
            if ch == quote and not (quote == '"' and i and raw[i - 1] == "\\"):
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(raw: str, path: str, line: int) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == '"':
        if len(raw) < 2 or raw[-1] != '"':
            raise ParseError(path, line, f"unterminated double-quoted string: {raw} (a quoted value must "
                             "close on the same line; for longer text use one quoted line or a '|' block)")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ParseError(path, line, f"bad double-quoted string: {e}") from None
    if raw[0] == "'":
        if len(raw) < 2 or raw[-1] != "'":
            raise ParseError(path, line, f"unterminated single-quoted string: {raw}")
        return raw[1:-1].replace("''", "'")
    if raw[0] in "{&*!|>":
        raise ParseError(path, line, f"unsupported YAML construct: {raw} (quote the value: \"...\")")
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw in ("null", "Null", "~"):
        return None
    if INT_RE.match(raw):
        return int(raw)
    return raw


def _split_inline_list(inner: str, path: str, line: int) -> list[Any]:
    items, buf, quote = [], [], None
    for i, ch in enumerate(inner):
        if quote:
            buf.append(ch)
            if ch == quote and not (quote == '"' and inner[i - 1] == "\\"):
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        elif ch in "[]{}":
            raise ParseError(path, line, "nested collections are not supported")
        else:
            buf.append(ch)
    if quote:
        raise ParseError(path, line, "unterminated quote in inline list")
    tail = "".join(buf)
    if tail.strip() or items:
        items.append(tail)
    out = []
    for it in items:
        if not it.strip():
            raise ParseError(path, line, "empty item in inline list")
        out.append(_scalar(it, path, line))
    return out


def parse(fm: str, path: str = "<frontmatter>", first_line: int = 2) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = fm.split("\n")
    i = 0
    while i < len(lines):
        ln = first_line + i
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise ParseError(path, ln, f"unexpected indentation: {line.strip()} (a value that continues on "
                             "the next line must be one quoted line or a '|' block; list items start with '- ')")
        m = KEY_RE.match(line)
        if not m:
            raise ParseError(path, ln, f"expected 'key: value', got: {line.strip()}")
        key, rest = m.group(1), _strip_comment(m.group(2) or "").strip()
        if key in data:
            raise ParseError(path, ln, f"duplicate key: {key}")
        i += 1
        if rest in ("|", ">", "|-", ">-"):
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
                block.append(lines[i].strip())
                i += 1
            while block and not block[-1]:
                block.pop()
            data[key] = ("\n" if rest[0] == "|" else " ").join(block)
            continue
        if rest.startswith("["):
            if not rest.endswith("]"):
                raise ParseError(path, ln, "inline list must close on the same line")
            data[key] = _split_inline_list(rest[1:-1], path, ln)
            continue
        if rest:
            if rest[0] not in "\"'":
                # YAML plain scalars may continue on more-indented lines; they fold with spaces.
                while (i < len(lines) and lines[i].strip() and lines[i][0] in " \t"
                       and not lines[i].lstrip().startswith(("- ", "#"))):
                    rest += " " + _strip_comment(lines[i].strip())
                    i += 1
            data[key] = _scalar(rest, path, ln)
            continue
        # empty value: block list or empty
        items: list[Any] = []
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                i += 1
                continue
            stripped = nxt.lstrip()
            if stripped.startswith("- ") or stripped == "-":
                item = _strip_comment(stripped[1:]).strip()
                if item.startswith(("[", "{")):
                    raise ParseError(path, first_line + i, "nested collections are not supported")
                items.append(_scalar(item, path, first_line + i))
                i += 1
                continue
            if nxt[0] in " \t":
                raise ParseError(path, first_line + i, f"nested maps are not supported: {stripped} "
                                 "(use a top-level key, or a list item quoted as one string: - \"a: b\")")
            break
        data[key] = items if items else None
    return data


def load(path: str | Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, body). Empty dict if no frontmatter."""
    p = Path(path)
    fm, body, _ = split(p.read_text(encoding="utf-8"))
    if fm is None:
        return {}, body
    return parse(fm, str(p)), body


def set_scalar(path: str | Path, key: str, value: str | None) -> None:
    """Rewrite one top-level scalar key in place, keeping every other byte."""
    p = Path(path)
    text = p.read_bytes().decode("utf-8")  # keep CRLF: read_text would translate it
    nl = "\r\n" if "\r\n" in text else "\n"
    fm, _, body_line = split(text)
    if fm is None:
        raise ParseError(str(p), 1, "no frontmatter")
    lines = text.replace("\r\n", "\n").split("\n")
    end = body_line - 2  # index of closing ---
    rendered = None if value is None else f"{key}: {dump_scalar(value)}"
    for idx in range(1, end):
        if re.match(rf"^{re.escape(key)}:(\s|$)", lines[idx]):
            if rendered is None:
                del lines[idx]
            else:
                lines[idx] = rendered
            break
    else:
        if rendered is not None:
            lines.insert(end, rendered)
    p.write_text(nl.join(lines), encoding="utf-8", newline="")


def dump_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    if s == "" or re.search(r"[:#\[\]{}\"',&*!|>%@`]|^\s|\s$|^-", s) or s in (
        "true", "false", "null", "~") or INT_RE.match(s):
        return json.dumps(s, ensure_ascii=False)
    return s
