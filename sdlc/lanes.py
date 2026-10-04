"""Risk lanes (ADR-0001): which check list a ticket PR runs, chosen from the ticket and the diff.

The lanes are ordered mechanical < standard < strict. A ticket declares one (or gets the
default its risk and type imply); the diff and an override can only raise it.

A mechanical ticket declares `transforms:`. The mechanical lane holds only when replaying
them on the base version of every changed file gives the head byte for byte: then the diff
is the transforms and nothing else, and the full suite plus a review of the transform list
stand in for red proof. Any residue raises the PR to standard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import gitutil, paths
from .artifacts import AC_RE, LANES, Ticket
from .config import Config

TRANSFORM_KINDS = ("literal", "rename", "move")
_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
# literal "<old>" -> "<new>"   (JSON strings)
_LITERAL_RE = re.compile(r'^literal\s+("(?:[^"\\]|\\.)*")\s*->\s*("(?:[^"\\]|\\.)*")$')
_RENAME_RE = re.compile(rf"^rename\s+({_IDENT})\s*->\s*({_IDENT})$")
_MOVE_RE = re.compile(r"^move\s+(\S+)\s*->\s*(\S+)$")


@dataclass
class Transform:
    kind: str
    old: str
    new: str

    def apply(self, text: str) -> str:
        if self.kind == "literal":
            return text.replace(self.old, self.new)
        if self.kind == "rename":
            return re.sub(rf"(?<![A-Za-z0-9_$]){re.escape(self.old)}(?![A-Za-z0-9_$])",
                          lambda _: self.new, text)
        return text


@dataclass
class Lane:
    name: str
    declared: str
    reasons: list[str] = field(default_factory=list)  # each raise, with its trigger
    residue: list[str] = field(default_factory=list)   # mechanical: lines the transforms do not produce


def rank(lane: str) -> int:
    return LANES.index(lane) if lane in LANES else LANES.index("standard")


def stricter(a: str, b: str) -> str:
    return a if rank(a) >= rank(b) else b


def parse_transforms(items: list[str]) -> tuple[list[Transform], list[str]]:
    """Parse a ticket's `transforms:`. Only literal, identifier and move kinds exist: a general
    regex with captures can encode any edit, so it would prove nothing."""
    import json

    out, errs = [], []
    for raw in items:
        s = raw.strip()
        if m := _LITERAL_RE.match(s):
            old, new = json.loads(m.group(1)), json.loads(m.group(2))
            if not old:
                errs.append(f"transform {raw!r}: the literal to replace is empty")
            elif old == new:
                errs.append(f"transform {raw!r} changes nothing")
            else:
                out.append(Transform("literal", old, new))
        elif m := _RENAME_RE.match(s):
            if m.group(1) == m.group(2):
                errs.append(f"transform {raw!r} changes nothing")
            else:
                out.append(Transform("rename", m.group(1), m.group(2)))
        elif (m := _MOVE_RE.match(s)) and (m.group(1) in {t.old for t in out if t.kind == "move"}
                                            or m.group(2) in {t.new for t in out if t.kind == "move"}):
            errs.append(f"transform {raw!r}: each path may be moved from, and moved to, once")
        elif m := _MOVE_RE.match(s):
            old, new = m.group(1), m.group(2)
            if any(ch in old + new for ch in "*?") or old.startswith(("/", "../")) or new.startswith(("/", "../")):
                errs.append(f"transform {raw!r}: a move names two repo-relative paths, not globs")
            elif old == new:
                errs.append(f"transform {raw!r} changes nothing")
            else:
                out.append(Transform("move", old, new))
        else:
            errs.append(f"transform {raw!r}: want 'literal \"old\" -> \"new\"', 'rename old -> new' "
                        "(identifiers) or 'move old/path -> new/path'")
    return out, errs


def _text(b: bytes) -> str | None:
    """`b` as text when it is valid UTF-8, else None (binary: transforms never apply)."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _first_difference(a: bytes, b: bytes) -> int:
    al, bl = a.split(b"\n"), b.split(b"\n")
    for i, (x, y) in enumerate(zip(al, bl), 1):
        if x != y:
            return i
    return min(len(al), len(bl)) + 1


def _same_blob(cfg: Config, rel: str, expected: bytes) -> bool:
    """The working-tree file is stored as exactly `expected` once git's own filters (such as
    core.autocrlf on Windows) apply: a checkout's line endings are not the branch's change."""
    import tempfile

    # A committed file is judged by its committed blob: checkout filters could turn a CRLF
    # blob back into LF and hide it. Only uncommitted edits go through the filters.
    committed = gitutil.show_bytes(cfg.root, "HEAD", "./" + rel)
    if committed is not None and (cfg.root / rel).read_bytes() == committed:
        return committed == expected  # the checkout is the blob, byte for byte: judge the blob
    now = gitutil.git(cfg.root, "hash-object", "--", rel, check=False).strip()
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/blob"
        with open(p, "wb") as fh:
            fh.write(expected)
        want = gitutil.git(cfg.root, "hash-object", "--no-filters", p, check=False).strip()
    return bool(now) and now == want


def _mode_changes(cfg: Config, mb: str) -> set[str]:
    """Files whose mode (e.g. the executable bit) differs from the merge base."""
    out = set()
    raw = gitutil.git(cfg.root, "diff", "--raw", "-z", "--no-renames", "--relative", mb, check=False)
    parts = raw.split("\0")
    for i in range(0, len(parts) - 1, 2):
        head, path = parts[i], parts[i + 1]
        fields = head.lstrip(":").split()
        if len(fields) >= 2 and "000000" not in fields[:2] and fields[0] != fields[1]:
            out.add(path)
    return out


def residue(cfg: Config, mb: str, changed: list[str], transforms: list[Transform],
            ignore: set[str]) -> list[str]:
    """Changes the transforms do not produce, one message each. `changed` is every file that
    differs from the merge base `mb`; `ignore` is bookkeeping the play writes (the ticket, its
    evidence and review). Byte for byte: line endings, invalid UTF-8 and file modes count."""
    moves = {t.old: t.new for t in transforms if t.kind == "move"}
    targets = {new: old for old, new in moves.items()}
    edits = [t for t in transforms if t.kind != "move"]
    out = []
    # A move moves: the source existed and is gone, the target did not exist and now does.
    # Otherwise a "move" is a copy (a new route) or overwrites a file (a stub over the real one).
    for old, new in moves.items():
        if gitutil.show_bytes(cfg.root, mb, "./" + old) is None:
            out.append(f"{old}: declared moved, but it does not exist on the base branch")
        if (cfg.root / old).exists():
            out.append(f"{old}: declared moved to {new}, but it still exists")
        if gitutil.show_bytes(cfg.root, mb, "./" + new) is not None:
            out.append(f"{new}: a move may not overwrite a file that exists on the base branch")
        if not (cfg.root / new).is_file():
            out.append(f"{new}: declared move target does not exist")
    for f in sorted(set(changed) - set(moves)):
        if f in ignore:
            continue
        now_p = cfg.root / f
        now = now_p.read_bytes() if now_p.is_file() else None
        before = gitutil.show_bytes(cfg.root, mb, "./" + targets.get(f, f))
        if before is None:
            out.append(f"{f}: added, and no declared move creates it")
            continue
        if now is None:
            out.append(f"{f}: deleted, and no declared move removes it")
            continue
        expected = before
        text = _text(before)
        if text is not None:
            for t in edits:
                text = t.apply(text)
            expected = text.encode("utf-8")
        if expected != now and not _same_blob(cfg, f, expected):
            out.append(f"{f}:{_first_difference(expected, now)}: differs from what the transforms produce")
    for f in sorted(_mode_changes(cfg, mb) - ignore):
        out.append(f"{f}: file mode changed")
    return out


def resolve(cfg: Config, t: Ticket, changed: list[str], mb: str | None, override: str = "",
            ignore: set[str] | None = None) -> Lane:
    """The effective lane: max(declared, classified from the diff, override)."""
    declared = t.lane if t.lane in LANES else "standard"
    lane = Lane(declared, declared)

    def raise_to(name: str, why: str) -> None:
        if rank(name) > rank(lane.name):
            lane.reasons.append(f"{lane.name} -> {name}: {why}")
            lane.name = name

    if override:
        raise_to(override, f"override --lane {override}")
    contracts = cfg.data["paths"]["contracts"]
    if contracts in changed:
        raise_to("strict", f"{contracts} changed (a contract change is strict, even as a rename)")
    for f in changed:
        hit = next((g for g in cfg.section("lanes").get("strict_paths", []) if paths.match(f, g)), None)
        if hit:
            raise_to("strict", f"{f} matches lanes.strict_paths {hit!r}")
            break
    if lane.name != "mechanical":
        return lane
    if mb is None:
        raise_to("standard", "no merge base to replay the transforms against")
        return lane
    transforms, errs = parse_transforms(t.transforms)
    if errs or not transforms:
        raise_to("standard", "; ".join(errs) or "a mechanical ticket declares no transforms:")
        return lane
    old = _ticket_at(cfg, mb, t)
    if (_acs(old) != dict(t.acs)) if old is not None else bool(t.acs):
        raise_to("standard", "the ticket adds or changes an acceptance criterion")
        return lane
    lane.residue = residue(cfg, mb, changed, transforms, ignore or set())
    if lane.residue:
        raise_to("standard", f"{len(lane.residue)} change(s) the declared transforms do not produce "
                             f"(first: {lane.residue[0]})")
    return lane


def _ticket_at(cfg: Config, ref: str, t: Ticket) -> dict | None:
    from . import fm

    text = gitutil.show(cfg.root, ref, "./" + cfg.rel(t.path))
    if text is None:
        return None
    try:
        head, _, _ = fm.split(text)
        return fm.parse(head or "")
    except fm.ParseError:
        return {}


def _acs(data: dict) -> dict[str, str]:
    out = {}
    for raw in data.get("acceptance_criteria") or []:
        m = AC_RE.match(str(raw).strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out
