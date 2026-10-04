"""`sdlc lint`: deterministic validation of every upstream artifact."""
from __future__ import annotations

import re
from pathlib import Path

from . import fm, paths
from .artifacts import (AC_RE, LANES, RISKS, STATUSES, TICKET_ID_RE, TYPES, VERDICTS, Issue, Repo,
                        Ticket)

REQUIRED_TICKET_KEYS = ("id", "title", "type", "status", "risk", "depends_on", "skills",
                        "requirements", "source_spec", "source_plan")
SPEC_HEADINGS = ("## Requirements", "## Open")
PLAN_HEADINGS = ("## Contracts", "## Shared modules", "## File map", "## Test strategy",
                 "## Ticket cuts", "## Rollback")
DOC_STATUSES = ("draft", "accepted", "superseded", "rejected")
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
        issues.extend(_unordered_writers(tickets, cfg.root))
    return issues


def _shared_module_owners(repo: Repo, plan: Path) -> list[Issue]:
    """Each shared module in a plan has one owner ticket that creates it. Without that, every
    ticket needing the concern writes its own copy (the planRoleFor x3 / createDb x5 failure)."""
    from .prompt import shared_module_rows

    out: list[Issue] = []
    mine = [t for t in repo.tickets.values() if str(t.data.get("source_plan", "")) == repo.cfg.rel(plan)]
    if not mine:
        return out  # not ticketized yet
    for path, owner, _ in shared_module_rows(repo.cfg, plan):
        t = repo.tickets.get(owner)
        if t is None:
            out.append(Issue("error", repo.cfg.rel(plan), f"shared module {path}: owner {owner!r} is not a ticket"))
        elif path not in t.files and not any(paths.match(path, a) for a in t.areas):
            out.append(Issue("error", repo.cfg.rel(plan), f"shared module {path}: owner {owner} does not list it in areas:"))
    return out


def _unordered_writers(tickets: dict[str, Ticket], root: Path | None = None) -> list[Issue]:
    """Two open tickets that write the same file must be ordered by depends_on; otherwise they
    build in parallel, conflict, and each implements the shared concern its own way."""
    def ancestors(tid: str, seen: set[str]) -> set[str]:
        for d in tickets[tid].depends_on:
            if d in tickets and d not in seen:
                seen.add(d)
                ancestors(d, seen)
        return seen

    anc = {tid: ancestors(tid, set()) for tid in tickets}
    open_ = sorted(tid for tid, t in tickets.items() if t.status != "done")
    # Areas are globs: two tickets overlap on any existing file both match, or on an entry both list.
    existing = paths.repo_files(root) if root is not None and open_ else []
    reach = {tid: {f for f in existing if paths.match_any(f, tickets[tid].areas)} for tid in open_}
    out = []
    for i, a in enumerate(open_):
        for b in open_[i + 1:]:
            both = sorted((set(tickets[a].areas) & set(tickets[b].areas)) | (reach[a] & reach[b]))
            if both and a not in anc[b] and b not in anc[a]:
                out.append(Issue("error", "tickets/", f"{a} and {b} both write {', '.join(both)} but neither "
                                 "depends on the other; add depends_on, or give the file one owner ticket"))
    return out


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
        out.extend(_shared_module_owners(repo, p))
    contracts = repo.contracts
    if not contracts.path.is_file():
        if repo.tickets:
            out.append(Issue("error", cfg.data["paths"]["contracts"], "missing CONTRACTS file"))
    elif repo.tickets:
        # A page/route owner that is not a ticket is never probed by smoke (it only probes
        # pages whose owner is being built or shipped), so a typo silently disables the probe.
        owners = [(r.key, r.attrs.get("owner")) for r in contracts.routes]
        owners += [(f"page {p}", a.get("owner")) for p, a in contracts.page_attrs.items()]
        for what, owner in owners:
            if owner and owner not in repo.tickets:
                out.append(Issue("error", cfg.rel(contracts.path), f"{what}: owner={owner} is not a ticket"))
    if contracts.path.is_file() and not (contracts.routes or contracts.tables or contracts.events):
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
    if str(d.get("test", "required")) not in ("required", "none"):
        err(f"test must be required or none, got {d.get('test')!r}")
    elif not t.test_play:
        served = [c for c in t.contracts if re.match(r"(?:[A-Z]+\s+)?/", c.split("#", 1)[-1].strip())]
        if served:
            err(f"test: none, but the ticket implements {', '.join(served)}; routes and pages need "
                "real-stack proof from the test play")
    if t.status == "blocked" and not str(d.get("blocked_by", "")).strip():
        err("status blocked needs a non-empty blocked_by")
    legacy = d.get("legacy")
    if legacy is not None:
        if str(legacy) != "v0":
            err(f"legacy must be v0, got {legacy!r}")
        elif t.status != "done":
            err("legacy: v0 is only for a ticket that shipped (status: done) under kit v0")
    shipped_v0 = legacy is not None and str(legacy) == "v0" and t.status == "done"
    if t.status == "done" and not shipped_v0:
        # `sdlc status ... done` enforces this; a hand-edited status must not skip it.
        try:
            rv = repo.review_for(t.id)
        except fm.ParseError:
            rv = None
        if rv is None or rv.verdict != "approve":
            err(f"status done needs {repo.cfg.data['paths']['reviews']}/{t.id}.md with verdict: approve")

    for dep in t.depends_on:
        if dep == t.id:
            err("depends on itself")
        elif dep not in repo.tickets:
            err(f"depends_on {dep} does not exist")

    if "areas" in d and "files" in d:
        err("areas: replaces files:; keep one of them")
    elif "areas" not in d and "files" not in d:
        err("missing key 'areas'")
    files, areas = t.files, t.areas
    if t.type not in ("test",) and not areas:
        err("areas: is empty")
    for f in files:
        if any(ch in f for ch in "*?"):
            err(f"files: entries are exact paths, not globs ({f}); use areas: for globs")
    for f in areas:
        if f.startswith(("/", "../")) or "\\" in f:
            err(f"areas: entry must be a repo-relative posix path or glob ({f})")
    if len(set(areas)) != len(areas):
        err("areas: has duplicates")

    lane = str(d.get("lane", "") or "")
    if lane and lane not in LANES:
        err(f"lane must be one of {LANES}, got {lane!r}")
    if lane == "mechanical":
        from .lanes import parse_transforms

        transforms, terrs = parse_transforms(t.transforms)
        for e in terrs:
            err(e)
        if not transforms and not terrs:
            err("lane: mechanical needs transforms: (the edits the engine replays to prove the diff)")
        if t.type == "spike":
            err("a spike cannot be mechanical")
    elif t.transforms:
        err("transforms: only apply to lane: mechanical")
    from .tickets import amendment_lines, parse_amendment

    for ln in amendment_lines(t.body):
        if parse_amendment(ln) is None:
            err(f"malformed amendment {ln.strip()!r}: want '- <kind> <target>: <reason>'")
    sf = d.get("split_from")
    if sf and str(sf) not in repo.tickets:
        err(f"split_from {sf} does not exist")

    acs = t.acs
    if t.type == "spike":
        qs = t.questions
        if not qs:
            err("a spike needs questions: ('Q-1: what we must learn')")
        for q, text in qs:
            if not q:
                err(f"question must be 'Q-<n>: <question>': {text!r}")
        if acs:
            err("a spike has questions:, not acceptance_criteria")
    elif not acs and lane != "mechanical":
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
    if len(acs) > MAX_ACS and not shipped_v0:
        err(f"{len(acs)} acceptance criteria > {MAX_ACS}; split the ticket")

    if not t.requirements and t.type not in ("chore", "ops", "spike") and lane != "mechanical":
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
