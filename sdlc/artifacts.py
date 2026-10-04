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
    def test_play(self) -> bool:
        """False when the lead marked the ticket `test: none` (no real-stack test play), and for
        spikes, which deliver findings, not behaviour."""
        return str(self.data.get("test", "required")) != "none" and self.type != "spike"

    @property
    def lane(self) -> str:
        """The lane the ticket declares, or the default its risk and type imply. The gate may
        still raise it from the diff (lanes.resolve)."""
        floor = "strict" if self.risk == "high" or self.type == "contract" else ""
        declared = str(self.data.get("lane", "") or "")
        if declared in LANES and floor:
            return floor  # risk: high and type: contract are strict, whatever the lane field says
        return declared or floor or "standard"

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
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if kind is None:
            m = FENCE_RE.match(line.strip())
            if m:
                kind = m.group(1)
                continue
            if in_tables and (tm := V0_TABLE_ROW_RE.match(line.strip())):
                c.tables.append(tm.group(1))
            if line.startswith("#"):
                h = line.lstrip("#").strip()
                in_tables = h.lower() == "tables"
                c.headings.append(h)
                rm = ROUTE_LINE_RE.match(h)
                if rm and line.startswith(("## ", "### ", "#### ")):
                    _add_route(c, cfg, path, i, rm, "heading")
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
        elif kind == "events":
            c.events.append(s.split()[0])
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
