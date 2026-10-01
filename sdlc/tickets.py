"""Ticket status machine and deterministic scheduling."""
from __future__ import annotations

from . import fm
from .artifacts import Repo, Ticket

# (from, to) -> roles allowed to make the move
TRANSITIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("draft", "ready"): ("lead",),
    ("ready", "in_progress"): ("build", "lead"),
    ("in_progress", "in_review"): ("build",),
    ("in_review", "in_progress"): ("build", "review", "lead"),
    ("in_review", "done"): ("merge", "lead"),
    ("blocked", "ready"): ("lead",),
}
ANY_TO_BLOCKED = ("build", "test", "review", "lead")


class TransitionError(RuntimeError):
    pass


def reachable(frm: str, to: str, role: str) -> bool:
    """Can `role` alone move a ticket from `frm` to `to` (in any number of legal steps)?"""
    if frm == to or (to == "blocked" and role in ANY_TO_BLOCKED):
        return True
    seen, todo = {frm}, [frm]
    while todo:
        cur = todo.pop()
        for (a, b), roles in TRANSITIONS.items():
            if a == cur and role in roles and b not in seen:
                if b == to:
                    return True
                seen.add(b)
                todo.append(b)
    return False


def check_transition(repo: Repo, t: Ticket, to: str, role: str, reason: str = "") -> None:
    frm = t.status
    if to == "blocked":
        if role not in ANY_TO_BLOCKED:
            raise TransitionError(f"role {role} may not block tickets")
        if not reason:
            raise TransitionError("blocking needs --reason")
        return
    allowed = TRANSITIONS.get((frm, to))
    if allowed is None:
        legal = sorted(b for (a, b) in TRANSITIONS if a == frm) + ["blocked"]
        raise TransitionError(f"{t.id}: {frm} -> {to} is not a legal move (from {frm}: {', '.join(legal)})")
    if role not in allowed:
        raise TransitionError(f"{t.id}: {frm} -> {to} needs role {'/'.join(allowed)}, not {role}")
    if to == "in_progress" and frm == "ready":
        pending = [d for d in t.depends_on if repo.tickets.get(d) and repo.tickets[d].status != "done"]
        if pending:
            raise TransitionError(f"{t.id}: depends_on not done: {', '.join(pending)}")
    if to == "done":
        rv = repo.review_for(t.id)
        if rv is None or rv.verdict != "approve":
            raise TransitionError(f"{t.id}: needs {repo.cfg.data['paths']['reviews']}/{t.id}.md with verdict: approve")


def set_status(repo: Repo, t: Ticket, to: str, role: str, reason: str = "") -> str:
    check_transition(repo, t, to, role, reason)
    frm = t.status
    fm.set_scalar(t.path, "status", to)
    fm.set_scalar(t.path, "blocked_by", reason if to == "blocked" else None)
    t.data["status"] = to
    return frm


def ready_queue(repo: Repo) -> list[Ticket]:
    """Tickets a build agent may start now, in deterministic order."""
    out = []
    for tid in sorted(repo.tickets):
        t = repo.tickets[tid]
        if t.status != "ready":
            continue
        if all(repo.tickets.get(d) is not None and repo.tickets[d].status == "done" for d in t.depends_on):
            out.append(t)
    # Lower risk and fewer dependents last: unblock the graph first.
    dependents = {tid: 0 for tid in repo.tickets}
    for t in repo.tickets.values():
        for d in t.depends_on:
            if d in dependents:
                dependents[d] += 1
    out.sort(key=lambda t: (-dependents[t.id], t.id))
    return out


def migrate_acs(path) -> int:
    """Number legacy acceptance criteria in place: '- text' -> '- "AC-n: text"'. Returns count changed."""
    import json
    import re
    from pathlib import Path

    p = Path(path)
    text = p.read_bytes().decode("utf-8")  # keep CRLF: read_text would translate it
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    out, in_block, n, changed = [], False, 0, 0
    for i, line in enumerate(lines):
        if i > 0 and line.strip() == "---":
            in_block = False
        if re.match(r"^acceptance_criteria:\s*$", line):
            in_block = True
            out.append(line)
            continue
        if in_block:
            m = re.match(r"^(\s*)-\s+(.*)$", line)
            if m:
                n += 1
                raw = m.group(2).strip()
                val = fm._scalar(raw, str(p), i + 1) if raw else ""
                if not re.match(r"^AC-\d+:\s", str(val)):
                    val = f"AC-{n}: {val}"
                    changed += 1
                out.append(f"{m.group(1)}- {json.dumps(str(val), ensure_ascii=False)}")
                continue
            if line and not line[0].isspace():
                in_block = False
        out.append(line)
    if changed:
        p.write_text(nl.join(out), encoding="utf-8", newline="")
    return changed
