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


def _norm(b: bytes | None) -> str | None:
    return None if b is None else b.decode("utf-8", "replace").replace("\r\n", "\n")


def _first_difference(a: str, b: str) -> int:
    al, bl = a.split("\n"), b.split("\n")
    for i, (x, y) in enumerate(zip(al, bl), 1):
        if x != y:
            return i
    return min(len(al), len(bl)) + 1


def residue(cfg: Config, mb: str, changed: list[str], transforms: list[Transform],
            ignore: set[str]) -> list[str]:
    """Changed files (or lines) the transforms do not produce, one message each. `changed` is
    every file that differs from the merge base `mb`; `ignore` is bookkeeping the play writes
    (the ticket, its evidence and review)."""
    moves = {t.old: t.new for t in transforms if t.kind == "move"}
    targets = {new: old for old, new in moves.items()}
    edits = [t for t in transforms if t.kind != "move"]
    out = []
    for f in sorted(changed):
        if f in ignore:
            continue
        now_p = cfg.root / f
        now = _norm(now_p.read_bytes()) if now_p.is_file() else None
        src = targets.get(f, f)
        before = _norm(gitutil.show_bytes(cfg.root, mb, "./" + src))
        if f in moves:
            if now is not None:
                out.append(f"{f}: declared moved to {moves[f]}, but it still exists")
            continue
        if before is None:
            out.append(f"{f}: added, and no declared move creates it")
            continue
        if now is None:
            out.append(f"{f}: deleted, and no declared move removes it")
            continue
        expected = before
        for t in edits:
            expected = t.apply(expected)
        if expected != now:
            out.append(f"{f}:{_first_difference(expected, now)}: differs from what the transforms produce")
    for old, new in moves.items():
        if old in changed and not (cfg.root / new).is_file():
            out.append(f"{new}: declared move target does not exist")
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
