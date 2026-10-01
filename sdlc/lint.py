"""`sdlc lint`: deterministic validation of every upstream artifact."""
from __future__ import annotations

import re
from pathlib import Path

from . import fm
from .artifacts import (AC_RE, RISKS, STATUSES, TICKET_ID_RE, TYPES, VERDICTS, Issue, Repo,
                        Ticket)

REQUIRED_TICKET_KEYS = ("id", "title", "type", "status", "risk", "depends_on", "files",
                        "skills", "requirements", "acceptance_criteria", "source_spec",
                        "source_plan")
SPEC_HEADINGS = ("## Requirements", "## Open")
PLAN_HEADINGS = ("## Contracts", "## Shared modules", "## File map", "## Test strategy",
                 "## Ticket cuts", "## Rollback")
DOC_STATUSES = ("draft", "accepted", "superseded", "rejected")
MAX_FILES = 8
MAX_ACS = 8


def lint_repo(repo: Repo, only_ticket: str | None = None) -> list[Issue]:
    issues: list[Issue] = []
    cfg = repo.cfg
    tickets = repo.tickets
    reqs = repo.requirements()
    issues.extend(repo.load_issues)
    issues.extend(repo.contracts.issues)

    if only_ticket is None:
        issues.extend(_lint_docs(repo))

    targets = [repo.ticket(only_ticket)] if only_ticket else list(tickets.values())
    for t in targets:
        issues.extend(lint_ticket(repo, t, reqs))

    if only_ticket is None:
        issues.extend(_cycles(tickets))
    return issues


def _lint_docs(repo: Repo) -> list[Issue]:
    cfg = repo.cfg
    out: list[Issue] = []
    for s in repo.specs:
        where = cfg.rel(s.path)
        _doc_status(s.data, where, out)
        _headings(s.body, SPEC_HEADINGS, where, out)
        if not s.requirements:
            out.append(Issue("error", where, "no requirements (want '- **F-001-1** testable statement')"))
        if s.status == "accepted" and re.search(r"\[OPEN\b", s.body):
            out.append(Issue("warn", where, "accepted spec still has [OPEN] items; tickets must not resolve them"))
    adir = cfg.path("arch")
    for p in sorted(adir.glob("plan*.md")) if adir.is_dir() else []:
        try:
            data, body = fm.load(p)
        except fm.ParseError as e:
            out.append(Issue("error", cfg.rel(p), f"{e.msg} (line {e.line})"))
            continue
        _doc_status(data, cfg.rel(p), out)
        _headings(body, PLAN_HEADINGS, cfg.rel(p), out)
    contracts = repo.contracts
    if not contracts.path.is_file():
        if repo.tickets:
            out.append(Issue("error", cfg.data["paths"]["contracts"], "missing CONTRACTS file"))
    elif not (contracts.routes or contracts.tables or contracts.events):
        out.append(Issue("warn", cfg.rel(contracts.path),
                         "no ```routes / ```tables / ```events blocks; drift and smoke checks have nothing to compare"))
    rdir = cfg.path("reviews")
    for p in sorted(rdir.glob("T-*.md")) if rdir.is_dir() else []:
        out.extend(lint_review_file(repo, p))
    return out


def _doc_status(data: dict, where: str, out: list[Issue]) -> None:
    st = data.get("status")
    if st not in DOC_STATUSES:
        out.append(Issue("error", where, f"frontmatter status must be one of {DOC_STATUSES}, got {st!r}"))


def _headings(body: str, required: tuple[str, ...], where: str, out: list[Issue]) -> None:
    lines = {ln.strip() for ln in body.split("\n")}
    for h in required:
        if h not in lines:
            out.append(Issue("error", where, f"missing section '{h}'"))


def lint_ticket(repo: Repo, t: Ticket, reqs: dict) -> list[Issue]:
    out: list[Issue] = []
    w = repo.cfg.rel(t.path)
    d = t.data

    def err(msg: str) -> None:
        out.append(Issue("error", w, msg))

    for k in REQUIRED_TICKET_KEYS:
        if k not in d:
            err(f"missing key '{k}'")
    if not TICKET_ID_RE.match(t.id):
        err(f"id {t.id!r} must look like T-001-01")
    if not str(d.get("title", "")).strip():
        err("empty title")
    if t.type not in TYPES:
        err(f"type must be one of {TYPES}, got {t.type!r}")
    if t.status not in STATUSES:
        err(f"status must be one of {STATUSES}, got {t.status!r}")
    if t.risk not in RISKS:
        err(f"risk must be one of {RISKS}, got {t.risk!r}")
    if t.status == "blocked" and not str(d.get("blocked_by", "")).strip():
        err("status blocked needs a non-empty blocked_by")

    for dep in t.depends_on:
        if dep == t.id:
            err("depends on itself")
        elif dep not in repo.tickets:
            err(f"depends_on {dep} does not exist")

    files = t.files
    if t.type not in ("test",) and not files:
        err("files: is empty")
    for f in files:
        if any(ch in f for ch in "*?"):
            err(f"files: entries are exact paths, not globs ({f}); put globs in shared:")
        if f.startswith(("/", "../")) or "\\" in f:
            err(f"files: entry must be a repo-relative posix path ({f})")
    if len(set(files)) != len(files):
        err("files: has duplicates")
    if len(files) > MAX_FILES:
        err(f"{len(files)} files > {MAX_FILES}; split the ticket")

    acs = t.acs
    if not acs:
        err("no acceptance_criteria")
    seen = set()
    for ac, text in acs:
        if not ac:
            err(f"acceptance criterion must be 'AC-<n>: <observable behaviour>': {text!r}")
            continue
        if ac in seen:
            err(f"duplicate {ac}")
        seen.add(ac)
        if len(text) < 12:
            err(f"{ac} is too short to be testable: {text!r}")
    if len(acs) > MAX_ACS:
        err(f"{len(acs)} acceptance criteria > {MAX_ACS}; split the ticket")

    if not t.requirements and t.type not in ("chore", "ops"):
        err("requirements: is empty (cite F-/N- ids from the spec)")
    for r in t.requirements:
        if r not in reqs:
            err(f"requirement {r} is not defined in any spec")

    for ref in t.contracts:
        if not repo.contracts.has(ref):
            err(f"contract {ref!r} is not declared in {repo.cfg.data['paths']['contracts']}")

    for key in ("source_spec", "source_plan", "source_intent"):
        v = d.get(key)
        if v and not (repo.cfg.root / str(v)).is_file():
            err(f"{key} {v} does not exist")
    for adr in t.get_list("source_adr"):
        if not (repo.cfg.root / str(adr)).is_file():
            err(f"source_adr {adr} does not exist")

    for s in t.skills:
        if not _skill_exists(repo, s):
            err(f"skill {s!r} not found (kit skills/, product skills/, or skills/vendor/)")
    if t.risk == "high" and not d.get("accepted_by"):
        out.append(Issue("warn", w, "risk: high ticket has no accepted_by (lead sign-off)"))
    return out


def _skill_exists(repo: Repo, name: str) -> bool:
    from .skills import resolve

    return resolve(repo.cfg, name) is not None


def _cycles(tickets: dict[str, Ticket]) -> list[Issue]:
    out: list[Issue] = []
    state: dict[str, int] = {}

    def visit(tid: str, stack: list[str]) -> None:
        state[tid] = 1
        for dep in tickets[tid].depends_on:
            if dep not in tickets:
                continue
            if state.get(dep) == 1:
                cyc = stack[stack.index(dep):] + [dep] if dep in stack else [tid, dep]
                out.append(Issue("error", "tickets/", "dependency cycle: " + " -> ".join(cyc)))
            elif dep not in state:
                visit(dep, stack + [dep])
        state[tid] = 2

    for tid in sorted(tickets):
        if tid not in state:
            visit(tid, [tid])
    return out


def lint_review_file(repo: Repo, p: Path) -> list[Issue]:
    w = repo.cfg.rel(p)
    out: list[Issue] = []
    try:
        data, body = fm.load(p)
    except fm.ParseError as e:
        return [Issue("error", w, f"{e.msg} (line {e.line})")]
    tid = p.stem
    t = repo.tickets.get(tid)
    if t is None:
        return [Issue("error", w, f"review for unknown ticket {tid}")]
    if data.get("ticket") != tid:
        out.append(Issue("error", w, f"frontmatter ticket must be {tid}"))
    if data.get("verdict") not in VERDICTS:
        out.append(Issue("error", w, f"verdict must be one of {VERDICTS}"))
    for k in ("reviewer", "commit"):
        if not str(data.get(k, "")).strip():
            out.append(Issue("error", w, f"missing {k}"))
    rows = {m.group(1) for m in re.finditer(r"^\|\s*(AC-\d+)\s*\|", body, re.M)}
    for ac, _ in t.acs:
        if ac and ac not in rows:
            out.append(Issue("error", w, f"AC table has no row for {ac}"))
    for h in ("## Acceptance criteria", "## Findings", "## Gate"):
        if h not in {ln.strip() for ln in body.split("\n")}:
            out.append(Issue("error", w, f"missing section '{h}'"))
    if data.get("verdict") == "request_changes" and not re.search(r"^\s*[-*]\s+\S", _section(body, "## Findings"), re.M):
        out.append(Issue("error", w, "request_changes needs at least one finding"))
    return out


def _section(body: str, heading: str) -> str:
    m = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1) if m else ""
