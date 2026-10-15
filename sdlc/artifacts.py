"""Load and model the upstream artifacts: specs, contracts, plans, tickets, reviews."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import fm
from .config import Config

TICKET_ID_RE = re.compile(r"^T-\d{3}-\d{2,3}$")
TICKET_FILE_RE = re.compile(r"^(T-\d{3}-\d{2,3})(?:-[a-z0-9-]+)?\.md$")
REQ_ID = r"[A-Z]{1,4}-\d{3}-\d+"
REQ_DEF_RE = re.compile(rf"^\s*[-*]\s+\*\*({REQ_ID})\*\*\s*(.*)$")
AC_RE = re.compile(r"^(AC-\d+):\s+(\S.*)$")
QUESTION_RE = re.compile(r"^(Q-\d+):\s+(\S.*)$")
AC_TAG_RE = re.compile(r"(T-\d{3}-\d{2,3})/(AC-\d+)")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
ROUTE_LINE_RE = re.compile(rf"^({'|'.join(METHODS)})\s+(/\S*)(.*)$")
FENCE_RE = re.compile(r"^```(routes|pages|tables|events)\s*$")
# v0 CONTRACTS: under a '## Tables' heading, a markdown table row whose first cell is `name`
V0_TABLE_ROW_RE = re.compile(r"^\|\s*`([A-Za-z0-9_]+)`\s*\|")

STATUSES = ("draft", "ready", "in_progress", "in_review", "done", "blocked")
TYPES = ("backend", "frontend", "fullstack", "contract", "test", "ops", "chore", "spike")
# Risk lanes, loosest first. The engine may raise a ticket's lane, never lower it (ADR-0001).
LANES = ("mechanical", "standard", "strict")
RISKS = ("low", "medium", "high")
VERDICTS = ("approve", "request_changes")


@dataclass
class Issue:
    level: str  # error | warn
    where: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.where}: {self.msg}"


@dataclass
class Ticket:
    id: str
    path: Path
    data: dict[str, Any]
    body: str

    def get_list(self, key: str) -> list[Any]:
        v = self.data.get(key)
        if v is None or v == "":
            return []
        return v if isinstance(v, list) else [v]

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))

    @property
    def type(self) -> str:
        return str(self.data.get("type", ""))

    @property
    def risk(self) -> str:
        return str(self.data.get("risk", "low"))

    @property
    def real_stack_proof(self) -> bool:
        """The ticket's AC must be proven through the real stack: false when the lead marked it
        `test: none`, and for spikes, which deliver findings, not behaviour."""
        return str(self.data.get("test", "required")) != "none" and self.type != "spike"

    @property
    def test_play(self) -> bool:
        """A separate test play gives that proof, except for test tickets: their build runs the
        real-stack suites itself and must carry the proof (Gate.plan, ac-coverage)."""
        return self.real_stack_proof and self.type != "test"

    @property
    def no_test_play_reason(self) -> str:
        """Why `test_play` is false, in words for prompts and refusals."""
        if str(self.data.get("test", "required")) == "none":
            return "marked test: none"
        if self.type == "spike":
            return "a spike: it delivers findings, not behaviour"
        return "a test ticket: its build ran the real-stack suites"

    @property
    def lane(self) -> str:
        """The lane the ticket declares, or the default its risk and type imply. The gate may
        still raise it from the diff (lanes.resolve)."""
        floor = "strict" if self.risk == "high" or self.type == "contract" else ""
        declared = str(self.data.get("lane", "") or "")
        if floor:
            return floor  # risk: high and type: contract are strict, whatever the lane field says
        return declared if declared in LANES else "standard"

    @property
    def areas(self) -> list[str]:
        """Globs the ticket expects to change. `files:` (exact paths) is read as areas until
        `sdlc migrate` rewrites it."""
        return [str(x) for x in self.get_list("areas")] or self.files

    @property
    def transforms(self) -> list[str]:
        return [str(x) for x in self.get_list("transforms")]

    @property
    def questions(self) -> list[tuple[str, str]]:
        """[(Q-n, text)] of a spike; malformed entries come back as ('', raw)."""
        out = []
        for raw in self.get_list("questions"):
            m = QUESTION_RE.match(str(raw).strip())
            out.append((m.group(1), m.group(2)) if m else ("", str(raw)))
        return out

    @property
    def depends_on(self) -> list[str]:
        return [str(x) for x in self.get_list("depends_on")]

    @property
    def files(self) -> list[str]:
        return [str(x) for x in self.get_list("files")]

    @property
    def shared(self) -> list[str]:
        return [str(x) for x in self.get_list("shared")]

    @property
    def skills(self) -> list[str]:
        return [str(x) for x in self.get_list("skills")]

    @property
    def requirements(self) -> list[str]:
        return [str(x) for x in self.get_list("requirements")]

    @property
    def contracts(self) -> list[str]:
        return [str(x) for x in self.get_list("contracts")]

    @property
    def acs(self) -> list[tuple[str, str]]:
        """[(AC-n, text)]; malformed entries come back as ('', raw)."""
        out = []
        for raw in self.get_list("acceptance_criteria"):
            m = AC_RE.match(str(raw).strip())
            out.append((m.group(1), m.group(2)) if m else ("", str(raw)))
        return out

    def ac_tags(self) -> list[str]:
        return [f"{self.id}/{ac}" for ac, _ in self.acs if ac]


@dataclass
class Requirement:
    id: str
    text: str
    spec: Path
    line: int


@dataclass
class Spec:
    path: Path
    data: dict[str, Any]
    body: str
    requirements: list[Requirement]

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))


@dataclass
class Route:
    method: str
    path: str
    attrs: dict[str, str]
    line: int

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class Contracts:
    path: Path
    routes: list[Route] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    page_attrs: dict[str, dict[str, str]] = field(default_factory=dict)
    headings: list[str] = field(default_factory=list)
    # What each declaration says, for contract-diff: the rest of a table/event line, the prose
    # under a '### METHOD /path' or '### /page' heading, and the lines no key owns.
    definitions: dict[str, str] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    rest: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def has(self, ref: str) -> bool:
        ref = ref.strip()
        if ref.startswith("#"):
            ref = ref[1:]
        if "#" in ref:  # legacy "CONTRACTS.md#Heading"
            ref = ref.split("#", 1)[1]
        norm = normalize_route_key(ref)
        return (
            norm in {r.key for r in self.routes}
            or ref in self.tables
            or ref in self.events
            or ref in self.pages
            or ref.lower() in {h.lower() for h in self.headings}
        )


@dataclass
class Review:
    path: Path
    data: dict[str, Any]
    body: str

    @property
    def verdict(self) -> str:
        return str(self.data.get("verdict", ""))


def normalize_route_key(ref: str) -> str:
    m = ROUTE_LINE_RE.match(ref.strip())
    if not m:
        return ref.strip()
    return f"{m.group(1)} {normalize_path(m.group(2))}"


def normalize_path(p: str) -> str:
    """Canonical route path: '{param}' segments become '{}' so names don't matter."""
    p = p.split("?", 1)[0]
    if len(p) > 1:
        p = p.rstrip("/")
    return re.sub(r"\{[^}/]*\}", "{}", p)


class Repo:
    """Lazy view over a product's artifacts."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.load_issues: list[Issue] = []
        self._tickets: dict[str, Ticket] | None = None
        self._specs: list[Spec] | None = None
        self._contracts: Contracts | None = None
        self._delivered: set[str] | None = None
        self._in_flight: dict[str, list[str]] | None = None

    # -- tickets ----------------------------------------------------------
    @property
    def tickets(self) -> dict[str, Ticket]:
        if self._tickets is None:
            self._tickets = {}
            tdir = self.cfg.path("tickets")
            for p in sorted(tdir.glob("*.md")) if tdir.is_dir() else []:
                m = TICKET_FILE_RE.match(p.name)
                if not m:
                    continue
                try:
                    data, body = fm.load(p)
                except fm.ParseError as e:
                    self.load_issues.append(Issue("error", self.cfg.rel(p), str(e.msg) + f" (line {e.line})"))
                    continue
                tid = str(data.get("id", ""))
                if tid != m.group(1):
                    self.load_issues.append(Issue("error", self.cfg.rel(p),
                                                  f"frontmatter id {tid!r} does not match file name"))
                    continue
                if tid in self._tickets:
                    self.load_issues.append(Issue("error", self.cfg.rel(p), f"duplicate ticket id {tid}"))
                    continue
                self._tickets[tid] = Ticket(tid, p, data, body)
        return self._tickets

    def ticket(self, tid: str) -> Ticket:
        t = self.tickets.get(tid)
        if t is None:
            raise SystemExit(f"no ticket {tid} under {self.cfg.data['paths']['tickets']}/")
        return t

    # -- specs ------------------------------------------------------------
    @property
    def specs(self) -> list[Spec]:
        if self._specs is None:
            self._specs = []
            ddir = self.cfg.path("design")
            for p in sorted(ddir.glob("spec*.md")) if ddir.is_dir() else []:
                try:
                    data, body = fm.load(p)
                except fm.ParseError as e:
                    self.load_issues.append(Issue("error", self.cfg.rel(p), f"{e.msg} (line {e.line})"))
                    continue
                _, _, start = fm.split(p.read_text(encoding="utf-8"))
                reqs = []
                for i, line in enumerate(body.split("\n")):
                    m = REQ_DEF_RE.match(line)
                    if m:
                        reqs.append(Requirement(m.group(1), m.group(2).strip(), p, start + i))
                self._specs.append(Spec(p, data, body, reqs))
        return self._specs

    def requirements(self) -> dict[str, Requirement]:
        out: dict[str, Requirement] = {}
        for s in self.specs:
            for r in s.requirements:
                if r.id in out:
                    self.load_issues.append(Issue("error", f"{self.cfg.rel(r.spec)}:{r.line}",
                                                  f"requirement {r.id} defined twice"))
                out[r.id] = r
        return out

    # -- contracts --------------------------------------------------------
    @property
    def contracts(self) -> Contracts:
        if self._contracts is None:
            self._contracts = parse_contracts(self.cfg.path("contracts"), self.cfg)
        return self._contracts

    # -- derived status (ADR-0001 section 5) -------------------------------
    def delivered(self) -> set[str]:
        """Tickets a commit on the base branch names in an `Sdlc-Ticket:` trailer: merged."""
        if self._delivered is None:
            from . import approval, gitutil

            self._delivered = set()
            if approval.records_mode(self.cfg):
                # Both refs: a local base that lags the remote must not hide merged tickets.
                for ref in self.bases():
                    self._delivered |= set(gitutil.trailer_values(self.cfg.root, ref, "Sdlc-Ticket"))
        return self._delivered

    def status_of(self, t: Ticket) -> str:
        """The ticket's status: stored for lead decisions (draft, ready, blocked) and for tickets
        shipped before status was derived (done); `done` once a merged commit names it."""
        if t.status != "done" and t.id in self.delivered():
            return "done"
        return t.status

    def bases(self) -> list[str]:
        from . import gitutil

        base = str(self.cfg.section("vcs").get("base", "main"))
        return [r for r in (base, f"origin/{base}")
                if gitutil.git(self.cfg.root, "rev-parse", "--verify", "-q", r, check=False).strip()]

    def in_flight(self) -> dict[str, list[str]]:
        """Records mode: ticket -> the unmerged branches (local or fetched) with a commit that names it
        in an `Sdlc-Ticket:` trailer. Fetch first to see other people's branches."""
        if self._in_flight is None:
            from . import approval, gitutil

            self._in_flight = {}
            bases = self.bases() if approval.records_mode(self.cfg) else []
            if bases:
                root = self.cfg.root
                # Refs already merged into a base cannot name an unmerged commit: skip them unread.
                # One --no-merged per call: git before 2.29 rejects a second one. A failed scan
                # raises: read as "nothing in flight", it would let a second build take the ticket.
                listed = [gitutil.git(root, "for-each-ref", "--format=%(refname)%09%(refname:short)%09%(symref)",
                                      f"--no-merged={b}", "refs/heads", "refs/remotes").splitlines()
                          for b in bases]
                refs = [line for line in listed[0] if all(line in other for other in listed[1:])]
                for line in refs:
                    full, short, sym = (line.split("\t") + ["", ""])[:3]
                    if sym or short in bases:
                        continue
                    out = gitutil.git(root, "log", "--format=%(trailers:key=Sdlc-Ticket,valueonly,separator=%x0A)",
                                      full, "--not", *bases, check=False)
                    for tid in sorted({v.strip() for v in out.splitlines() if v.strip()}):
                        self._in_flight.setdefault(tid, []).append(short)
        return self._in_flight

    def tracked_status(self, t: Ticket) -> str:
        """status_of, and `in_progress` for a ready ticket that an unmerged branch names (records
        mode). For people and scheduling: checks that judge a branch use status_of."""
        s = self.status_of(t)
        return "in_progress" if s == "ready" and t.id in self.in_flight() else s

    def pending_deps(self, t: Ticket) -> list[str]:
        """The tickets `t` depends on that are not done (an unknown id counts as not done)."""
        return [d for d in t.depends_on if d not in self.tickets or self.status_of(self.tickets[d]) != "done"]

    # -- reviews ----------------------------------------------------------
    def review_for(self, tid: str) -> Review | None:
        p = self.cfg.path("reviews") / f"{tid}.md"
        if not p.is_file():
            return None
        data, body = fm.load(p)
        return Review(p, data, body)


def parse_contracts(path: Path, cfg: Config, text: str | None = None) -> Contracts:
    """CONTRACTS at `path`, or `text` as if it were that file (e.g. the base branch's version)."""
    c = Contracts(path)
    if text is None:
        if not path.is_file():
            return c
        text = path.read_text(encoding="utf-8")
    kind = None
    in_tables = False  # inside a v0 '## Tables' section
    section = None     # the heading text whose prose this line belongs to
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if kind is None:
            m = FENCE_RE.match(line.strip())
            if m:
                kind = m.group(1)
                section = None
                continue
            if in_tables and (tm := V0_TABLE_ROW_RE.match(line.strip())):
                c.tables.append(tm.group(1))
                c.definitions[f"table {tm.group(1)}"] = line.strip()
                continue
            if line.startswith("#"):
                h = line.lstrip("#").strip()
                in_tables = h.lower() == "tables"
                c.headings.append(h)
                rm = ROUTE_LINE_RE.match(h)
                if rm and line.startswith(("## ", "### ", "#### ")):
                    _add_route(c, cfg, path, i, rm, "heading")
                section = h if (rm or h.startswith("/")) and line.startswith(("### ", "#### ")) else None
                if section is None:
                    c.rest.append(line)
                continue
            if section is not None:
                c.sections[section] = c.sections.get(section, "") + line + "\n"
            else:
                c.rest.append(line)
            continue
        s = line.strip()
        if s.startswith("```"):
            kind = None
            continue
        if not s or s.startswith("#"):
            continue
        if kind == "routes":
            m = ROUTE_LINE_RE.match(s)
            if not m:
                c.issues.append(Issue("error", f"{cfg.rel(path)}:{i}",
                                      f"bad route line (want 'METHOD /path key=value...'): {s}"))
                continue
            _add_route(c, cfg, path, i, m, "block")
        elif kind == "tables":
            c.tables.append(s.split()[0])
            c.definitions[f"table {s.split()[0]}"] = " ".join(s.split()[1:])
        elif kind == "events":
            c.events.append(s.split()[0])
            c.definitions[f"event {s.split()[0]}"] = " ".join(s.split()[1:])
        elif kind == "pages":
            if not s.startswith("/"):
                c.issues.append(Issue("error", f"{cfg.rel(path)}:{i}", f"page must start with '/': {s}"))
                continue
            parts = s.split()
            c.pages.append(parts[0])
            c.page_attrs[parts[0]] = dict(kv.split("=", 1) for kv in parts[1:] if "=" in kv)
    if kind is not None:
        c.issues.append(Issue("error", cfg.rel(path), f"unclosed ```{kind} block"))
    return c


def _add_route(c: Contracts, cfg: Config, path: Path, i: int, m: re.Match, origin: str) -> None:
    """Routes come from ```routes blocks and from '### METHOD /path' headings. A heading
    that documents a block route is the same route; two declarations of one kind clash."""
    attrs = dict(kv.split("=", 1) for kv in m.group(3).split() if "=" in kv)
    r = Route(m.group(1), normalize_path(m.group(2)), attrs, i)
    r.attrs["raw_path"] = m.group(2)
    r.attrs["origin"] = origin
    for prev in c.routes:
        if prev.key != r.key:
            continue
        if prev.attrs["origin"] == origin:
            c.issues.append(Issue("error", f"{cfg.rel(path)}:{i}", f"duplicate route {r.key} (also line {prev.line})"))
        elif origin == "block":
            c.routes[c.routes.index(prev)] = r  # block line carries the attrs
        return
    c.routes.append(r)
