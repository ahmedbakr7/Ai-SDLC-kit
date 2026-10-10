"""`sdlc gate <play> [ticket]`: every check a play must pass, run the same way everywhere.

The gate is the definition of done. Agents do not report "green"; they run this
and the evidence file it writes is what review, CI and merge look at.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from . import approval, baseline, config, extract, fm, gitutil, lanes, lint, paths, presets, tickets, waivers
from .artifacts import AC_RE, Repo, Ticket, normalize_path
from .config import Config

TICKET_PLAYS = ("build", "test", "review")
EVIDENCE_PLAYS = ("build", "test")  # plays whose passing evidence is committed under evidence/
# `gate pr <id>` judges one ticket's whole branch (build + test + review + the merge's `done`);
# without a ticket, a lead PR (lead_write_set).
PR_ROLES = ("build", "test", "review", "merge")
COMMAND_CHECKS = ("lint", "typecheck", "unit", "integration", "e2e", "build", "duplication")
JUNIT_CHECKS = ("unit", "integration", "e2e")
RUN_DIR = ".sdlc-run"
SPIKE_DOCS = (".md", ".markdown", ".rst", ".txt")  # what a spike may write: findings, not code
RED_BACKUP = "red-backup"  # under RUN_DIR: files ac-red reverted, until it puts them back
_JS_TEST = r"\b(?:it|test|describe|suite)(?:\.\w+)*"  # it.only, describe.concurrent.only, ...
BUILTIN_TEST_FORBID = [
    {"regex": _JS_TEST + r"\.only\s*\(|\bf(?:it|describe)\s*\(", "message": "focused test (.only) hides the rest of the suite"},
    {"regex": _JS_TEST + r"\.(?:skip|skipIf|runIf|todo)\s*\(|\bx(?:it|describe|test)\s*\(",
     "message": "skipped or conditionally skipped test"},
    {"regex": r"@pytest\.mark\.skip(?:if)?\b|\bpytest\.skip\s*\(|@unittest\.skip(?:If|Unless)?\b|\.skipTest\s*\(",
     "message": "skipped or conditionally skipped test"},
    # Inverted tests report "passed" when their assertion fails, so a tagged one proves the opposite.
    {"regex": _JS_TEST + r"\.fails\s*\(|@unittest\.expectedFailure\b|@pytest\.mark\.xfail\b|\bpytest\.xfail\s*\(",
     "message": "expected-failure test passes when its assertion fails"},
]


@dataclass
class Check:
    name: str
    status: str = "pass"  # pass | fail | skip
    summary: str = ""
    details: list[str] = field(default_factory=list)
    ms: int = 0
    log: str = ""
    known: list[str] = field(default_factory=list)  # baselined failures this run still has
    waived: list[str] = field(default_factory=list)  # failures a waiver covered: "key: W-1 (owner, expires)"


@dataclass
class TestCase:
    name: str
    status: str  # passed | failed | skipped
    source: str


class Gate:
    def __init__(self, cfg: Config, play: str, ticket_id: str | None, base: str | None,
                 only: list[str] | None = None, verbose: bool = False, since: str | None = None,
                 ignore_baseline: bool = False, lane: str = ""):
        recover(cfg.root)  # before anything reads the tree
        self.base = base or cfg.section("vcs").get("base", "main")
        self.base_given = base is not None
        self.play = play
        self.config_note = ""
        if play in ("ci", "pr") or (ticket_id and play in TICKET_PLAYS):
            cfg = self._trusted_config(cfg)
        self.cfg = cfg
        # Approvals outside the tree (ADR-0001 step 2): no committed evidence, derived status.
        self.records = approval.records_mode(cfg)
        self.repo = Repo(cfg)
        self.play = play
        self.ticket: Ticket | None = self.repo.ticket(ticket_id) if ticket_id else None
        self.only = only
        self.verbose = verbose
        self.run_dir = cfg.root / RUN_DIR
        (self.run_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.testcases: list[TestCase] = []
        self.junit_used: dict[str, bool] = {}
        self.checks: list[Check] = []
        self._changed: list[str] | None = None
        # test and review answer for what they changed after the earlier plays' evidence was
        # committed, not for the build's own diff against the base branch. `sdlc run` passes
        # the HEAD it saw before the agent started; without it this falls back to the commit
        # history, which an agent with git access could shape (CI judges the whole PR instead).
        if since is None and self.ticket and play in ("test", "review"):
            plays = ("build",) if play == "test" else EVIDENCE_PLAYS
            since = (_play_commit(cfg, self.base, plays) if self.records
                     else _evidence_commit(cfg, self.ticket.id, plays))
        self.since = since
        # The branch's baseline; `immutable` proves it only shrinks against the base branch's.
        bl = baseline.path(cfg.root, cfg.data["paths"])
        self.baseline_rel = cfg.rel(bl)
        self.baseline = {} if ignore_baseline else baseline.load(cfg.root, self.baseline_rel)
        # Waivers apply once they are on the base branch, unchanged (ADR-0002).
        self.waivers_rel = cfg.rel(waivers.path(cfg.root, cfg.data["paths"]))
        try:
            wbase: str | None = gitutil.merge_base(cfg.root, self.base)
        except gitutil.GitError:
            wbase = None
        self.waivers = (waivers.State() if ignore_baseline else
                        waivers.state(cfg.root, self.waivers_rel, wbase, waivers.max_days(cfg.section("waivers")),
                                      renewals=not presets.hardened(cfg.data)))
        # The lane is judged on the whole branch against the base, whichever play runs.
        self.lane: lanes.Lane | None = None
        self.mb: str | None = None
        self.base_ticket: dict | None = None  # the ticket as the base branch has it (None: new)
        if self.ticket and play in (*TICKET_PLAYS, "pr"):
            if lane and lane not in lanes.LANES:
                raise SystemExit(f"--lane must be one of {', '.join(lanes.LANES)}, got {lane!r}")
            try:
                self.mb = gitutil.merge_base(cfg.root, self.base)
                # Committed blobs too: checkout filters can make a committed change look clean.
                branch = sorted(set(gitutil.changed_files(cfg.root, self.base))
                                | set(gitutil.committed_between(cfg.root, self.mb)))
            except gitutil.GitError:
                branch = []
            if self.mb:
                self.base_ticket = lanes._ticket_at(cfg, self.mb, self.ticket)
            self.lane = lanes.resolve(cfg, self.ticket, branch, self.mb, override=lane,
                                      ignore=self.bookkeeping())

    # -- plumbing ---------------------------------------------------------
    def _trusted_config(self, cfg: Config) -> Config:
        """Ticket plays and CI are judged by the base branch's sdlc.toml, never by the branch
        under test: otherwise the change being gated could drop a check or swap a command
        (a PR adding `[gate] ci = ["artifacts"]` passed its own CI). A config change takes
        effect once it is on the base branch."""
        try:
            mb = gitutil.merge_base(cfg.root, self.base)
        except gitutil.GitError as e:
            if self.base_given:  # CI names its base: a shallow clone must not mean "trust the PR"
                raise SystemExit(f"{e}; the gate needs the base branch's history (fetch-depth: 0)") from None
            self.config_note = f"{e}; judged with this branch's {config.CONFIG_NAME}"
            return cfg
        if self.play == "ci" and mb == gitutil.head(cfg.root):
            return cfg  # on the base branch itself (a push, or the lead editing config locally)
        committed = gitutil.show(cfg.root, mb, "./" + config.CONFIG_NAME)
        if committed is None:
            return cfg
        trusted = config.load(cfg.root, text=committed)
        if trusted.data != cfg.data:
            self.config_note = (f"{config.CONFIG_NAME} differs from {self.base}; this gate used the "
                                f"{self.base} version. Config changes go to {self.base} first, not in a ticket.")
        return trusted

    def bookkeeping(self) -> set[str]:
        """Files the ticket flow writes besides the work: the ticket, its evidence and review,
        and the baseline (pruned)."""
        t, p = self.ticket, self.cfg.data["paths"]
        if not t:
            return set()
        return {self.cfg.rel(t.path), f"{p['reviews']}/{t.id}.md", self.baseline_rel,
                *(f"{p['evidence']}/{t.id}.{play}.json" for play in EVIDENCE_PLAYS)}

    def build_areas(self) -> tuple[list[str], list[str]]:
        """(globs, exact paths) of the ticket's areas as the base branch has them: widening the
        areas in the PR is free, but it never silences the out-of-area flags the review owes.
        A ticket created on this branch uses its own."""
        t, d = self.ticket, self.base_ticket
        if d is None:
            return t.areas + t.shared, t.files
        def lst(k: str) -> list[str]:
            v = d.get(k)
            return [str(x) for x in (v if isinstance(v, list) else [v] if v else [])]
        return (lst("areas") or lst("files")) + lst("shared"), lst("files")

    def plan(self) -> list[str]:
        g = self.cfg.section("gate")
        if self.play not in g:
            raise SystemExit(f"no gate defined for play {self.play!r}")
        names = list(g[self.play])
        if self.ticket and self.play == "build":
            names = self._build_list(names)
        if self.ticket and self.play == "pr" and self.records:
            # Nothing trusts committed evidence: the PR runs the lane's build checks and, where
            # the ticket has a test play, the test play's checks, on its own head. Approval is
            # the separate `sdlc approval` check, re-run as reviews arrive.
            names = self._build_list(list(g["build"]))
            if self.ticket.test_play and not (self.lane and self.lane.name == "mechanical"):
                # The test play's order (its suites run before ac-coverage reads them), then the
                # build's own checks (ac-red, duplication) after.
                names = list(g["test"]) + [n for n in names if n not in g["test"]]
            names += [n for n in g["pr"] if n not in names]  # checks the lead added to the PR gate
            names = [n for n in names if n != "review-file"]
        if self.lane and self.lane.name == "strict" and self.play in ("build", "test", "pr"):
            names += [n for n in g.get("strict", []) if n not in names]
        if self.lane:
            # Every ticket play reports (and pr enforces) its lane; config cannot leave it out.
            names = ["lane"] + [n for n in names if n != "lane"]
        if self.only:
            names = [n for n in names if n in self.only]
        return names

    def _build_list(self, default: list[str]) -> list[str]:
        g = self.cfg.section("gate")
        if self.ticket.type == "spike":
            return list(g.get("spike", default))
        if self.lane and self.lane.name == "mechanical":
            return list(g.get("mechanical", default))
        if self.ticket.type == "test":
            # A test ticket changes tests only: its AC may be provable by a real-stack suite alone,
            # so its build runs those suites before ac-coverage reads the results. It has no test
            # play (Ticket.test_play): the build is that play.
            suites = real_stack_suites(self.cfg)
            names = [n for n in default if n not in suites]  # a configured later position moves too
            at = names.index("ac-coverage") if "ac-coverage" in names else len(names)
            return names[:at] + suites + names[at:]
        return default

    def changed(self) -> list[str]:
        if self._changed is None:
            if self.since:
                changed = gitutil.changed_since(self.cfg.root, self.since)
                try:
                    # Files merged in from the base branch since the earlier play are not this
                    # play's change: keep only what still differs from the base.
                    ours = set(gitutil.changed_files(self.cfg.root, self.base))
                    new = set(gitutil.untracked(self.cfg.root))
                    # A file both sides edited counts only if this branch's own change to it moved.
                    changed = [f for f in changed if f in ours and (
                        f in new or not gitutil.same_branch_change(self.cfg.root, self.base, self.since, f))]
                except gitutil.GitError:
                    pass
                self._changed = changed
            else:
                self._changed = gitutil.changed_files(self.cfg.root, self.base)
        return self._changed

    def run(self, on_check: Callable[[Check], None] | None = None) -> dict:
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for name in self.plan():
            fn = getattr(self, "check_" + name.replace("-", "_"), None)
            c = Check(name)
            t0 = time.monotonic()
            if fn is not None:
                try:
                    fn(c)
                except Exception as e:  # a crashing check is a failing check
                    c.status, c.summary = "fail", f"check crashed: {type(e).__name__}: {e}"
            elif name in COMMAND_CHECKS:
                self._command(c)
            else:
                c.status, c.summary = "fail", f"unknown check {name!r}"
            c.ms = int((time.monotonic() - t0) * 1000)
            self._apply_baseline(c)
            self.checks.append(c)
            if on_check:
                on_check(c)
        for extra in (self._check_waivers(), self._check_trailers()):
            if extra is not None:
                self.checks.append(extra)
                if on_check:
                    on_check(extra)
        ok = all(c.status != "fail" for c in self.checks)
        ev = {
            "kit_evidence": 1,
            "play": self.play,
            "ticket": self.ticket.id if self.ticket else None,
            "commit": gitutil.head(self.cfg.root),
            "dirty": gitutil.is_dirty(self.cfg.root),
            "base": self.base,
            "started": started,
            "result": "pass" if ok else "fail",
            "checks": [asdict(c) for c in self.checks],
            "ac": self.ac_matrix() if self.ticket else self._shipped_matrix(),
            # Whether a passing real-stack test carries one of the ticket's AC tags: a test
            # ticket's build is its real-stack proof, and approval reads this, not the suites run.
            "real_stack_proof": bool(self.ticket) and self._real_stack_proof(self.ticket.id),
            "config_note": self.config_note,
            "lane": self.lane.name if self.lane else "",
            "baseline": self.baseline_rel if self.baseline else "",
        }
        if self.only:
            ev["partial"] = True  # a subset of the play's checks proves nothing about the play
        self.write_evidence(ev)
        return ev

    def findings(self, c: Check) -> list[str]:
        """Stable keys for what failed in `c` (sdlc-baseline.json entries)."""
        if c.name in ("lint", "typecheck"):
            log = self.cfg.root / c.log if c.log else None
            keys = baseline.tool_findings(log.read_text(encoding="utf-8", errors="replace")) if log and log.is_file() else []
        elif c.name in JUNIT_CHECKS:
            keys = [tc.name for tc in self.testcases if tc.source == c.name and tc.status == "failed"]
        elif c.name in COMMAND_CHECKS:
            keys = []
        else:
            keys = baseline.detail_findings(c.details)
        return keys or [baseline.whole(c.name)]

    def _apply_baseline(self, c: Check) -> None:
        """A check fails only on failures sdlc-baseline.json does not list and no waiver on the
        base branch covers. On the full scan (gate ci), entries that stopped failing fail it too,
        so the baseline only shrinks, and so does a waiver that covers nothing."""
        known = self.baseline.get(c.name, [])
        ws = self.waivers.for_check(c.name)
        if (not known and not ws) or c.name not in baseline.BASELINE_CHECKS or c.status == "skip":
            return
        now = self.findings(c) if c.status == "fail" else []
        new, stale = baseline.compare(known, now)
        new, covered, unused = waivers.apply(ws, new)
        c.waived = [f"{k}: {w.label()}" for k, w in covered]
        if new:
            c.status = "fail"
            c.summary = f"{len(new)} new failure(s) not in {self.baseline_rel}; {c.summary}"
            c.details = [f"new: {k}" for k in new] + [f"waived: {x}" for x in c.waived] + c.details
            return
        if c.status == "fail":
            waived_keys = Counter(k for k, _ in covered)
            c.status, c.known = "pass", sorted((Counter(now) - waived_keys).elements())
            parts = [f"BASELINED: {len(c.known)} known failure(s) from {self.baseline_rel}"] if c.known else []
            parts += [f"WAIVED: {len(covered)} failure(s) under {self.waivers_rel}"] if covered else []
            c.summary = f"{', '.join(parts)}, none new ({c.summary})"
            c.details = [f"known: {k}" for k in c.known] + [f"waived: {x}" for x in c.waived]
        if self.play == "ci" and not self.only and (stale or unused):
            c.status = "fail"
            why = []
            if stale:
                why.append(f"{len(stale)} baselined failure(s) no longer fail; run `sdlc baseline --prune` and "
                           f"commit {self.baseline_rel} (it only shrinks)")
            if unused:
                why.append(f"{len(unused)} waiver(s) cover nothing; remove them from {self.waivers_rel}")
            c.summary = "; ".join(why)
            c.details = ([f"fixed: {k}" for k in stale] + [f"stale waiver: {w.id} ({w.key})" for w in unused]
                         + c.details)

    def _check_waivers(self) -> Check | None:
        """The waiver file itself: `gate ci` fails on an invalid, expired or over-long waiver;
        every other gate reports it. Absent when there is no waiver file on either side."""
        s = self.waivers
        if not (s.active or s.pending or s.problems or s.warnings):
            return None
        c = Check("waivers")
        strict = self.play == "ci" and not self.only
        c.details = ([("ERROR " if strict else "WARN ") + p for p in s.problems] + [f"WARN {w}" for w in s.warnings]
                     + [f"pending: {wid} applies once it is on {self.base}" for wid in s.pending])
        if s.problems and strict:
            c.status, c.summary = "fail", f"{len(s.problems)} waiver problem(s) in {self.waivers_rel}"
        else:
            c.summary = (f"{len(s.active)} waiver(s) apply" + (f", {len(s.problems)} problem(s) reported"
                                                              if s.problems else "")
                         + (f", {len(s.warnings)} expiring soon" if s.warnings else ""))
        return c

    def _check_trailers(self) -> Check | None:
        """`gate ci` fails when a merged commit names a ticket outside its trailers: a squash
        merge folds the PR's `Sdlc-Ticket:` trailers into the body, so derived status never sees
        the ticket as done and `sdlc next` offers it again. A ticket another commit delivers as a
        trailer is visible, so it is not reported: merging the PR's own commits with a merge
        commit is the fix, and needs no revert (one would regrow a baseline the PR pruned)."""
        if self.play != "ci" or self.only or not self.records:
            return None
        delivered = set(gitutil.trailer_values(self.cfg.root, "HEAD", "Sdlc-Ticket"))
        buried = [(sha, missed) for sha, ids in gitutil.buried_trailers(self.cfg.root, "HEAD", "Sdlc-Ticket")
                  if (missed := [i for i in ids if i not in delivered])]
        if not buried:
            return None
        c = Check("trailers")
        c.status = "fail"
        c.summary = (f"{len(buried)} merged commit(s) name Sdlc-Ticket outside their trailers (a squash merge?): "
                     "status cannot see those tickets")
        c.details = [f"{sha[:12]} names {', '.join(ids)} in its body, not as a trailer" for sha, ids in buried]
        c.details.append("fix: merge the PR's own commits with a merge commit; no revert is needed "
                         "(never squash or rebase a ticket PR)")
        return c

    def _shipped_matrix(self) -> dict:
        """gate ci's AC proof for every shipped ticket: CI evidence `sdlc trace` reads when status
        is derived (nothing is committed under evidence/ then)."""
        if self.play != "ci" or not self.records:
            return {}
        out: dict = {}
        for _, t in sorted(self.repo.tickets.items()):
            if self.repo.status_of(t) == "done":
                out.update(self.ac_matrix(t))
        return out

    def write_evidence(self, ev: dict) -> Path:
        name = f"{self.ticket.id}.{self.play}.json" if self.ticket else f"{self.play}.json"
        dest = self.run_dir / name
        if self.ticket and self.play in EVIDENCE_PLAYS and not ev.get("partial") and not self.records:
            dest = self.cfg.path("evidence") / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(ev, indent=2) + "\n", encoding="utf-8")
        ev["path"] = self.cfg.rel(dest)
        return dest

    # -- checks -----------------------------------------------------------
    def check_artifacts(self, c: Check) -> None:
        issues = lint.lint_repo(self.repo)
        errs = [i for i in issues if i.level == "error"]
        c.details = [str(i) for i in issues]
        if errs:
            c.status, c.summary = "fail", f"{len(errs)} artifact error(s); run `sdlc lint`"
        else:
            c.summary = f"artifacts valid ({len(issues)} warning(s))"
        if self.ticket and self.play == "build":
            t = self.ticket
            if self.records:
                # Status is derived: the lead made the ticket ready (or a mechanical ticket is
                # created in its own PR); merged means done, and done tickets are not rebuilt.
                if self.repo.status_of(t) == "done" or t.status not in ("ready",):
                    c.status = "fail"
                    c.details.append(f"{t.id} is {self.repo.status_of(t)}; a build starts from a ready ticket")
            elif t.status not in ("in_progress", "in_review"):
                c.status = "fail"
                c.details.append(f"{t.id} status is {t.status}; run `sdlc status {t.id} in_progress --as build` first")
            pending = [d for d in t.depends_on if self.repo.tickets.get(d)
                       and self.repo.status_of(self.repo.tickets[d]) != "done"]
            if pending:
                c.status = "fail"
                c.details.append(f"depends_on not done: {', '.join(pending)}")

    def roles(self) -> tuple[str, ...]:
        """Ticket plays whose write sets apply: one, or all of them for a whole ticket PR."""
        return PR_ROLES if self.play == "pr" else (self.play,)

    def allowed(self, roles: tuple[str, ...] | None = None) -> tuple[list[str], set[str]]:
        """(glob patterns, exact paths) the current play (or `roles`) may change."""
        cfg, t = self.cfg, self.ticket
        paths = cfg.section("paths")
        globs = list(cfg.section("scope").get("always_allowed", []))
        # Any play may prune the baseline (`immutable` refuses growth). A change to the waivers
        # makes the PR strict, so it needs a lead approval (lanes.resolve).
        exact: set[str] = {self.baseline_rel, self.waivers_rel}
        if not t:
            if self.play == "pr":
                globs += lead_write_set(cfg)
            return globs, exact
        tests = cfg.section("tests")
        for play in roles or self.roles():
            # A play may write only its own evidence: test/review must not rewrite the build's proof.
            if play in EVIDENCE_PLAYS:
                exact.add(f"{paths['evidence']}/{t.id}.{play}.json")
            if play == "build":
                area_globs, area_files = self.build_areas()
                exact |= set(area_files)
                globs += area_globs
            elif play == "test":
                globs += tests.get("integration_globs", [])
            elif play == "review":
                exact.add(f"{paths['reviews']}/{t.id}.md")
        return globs, exact

    def _earlier_play_outputs(self) -> list[Callable[[str], bool]]:
        """A rebuild (review asked for changes) runs on a branch that already holds the test
        and review plays' files. They are not the build's to change, but they may stay, as
        long as the build has not touched them since that play committed."""
        t, out = self.ticket, []
        anchors = {"test": f"{self.cfg.data['paths']['evidence']}/{t.id}.test.json",
                   "review": f"{self.cfg.data['paths']['reviews']}/{t.id}.md"}
        for play, anchor in anchors.items():
            done_at = (_play_commit(self.cfg, self.base, (play,)) or "" if self.records else
                       gitutil.git(self.cfg.root, "log", "-1", "--format=%H", "--", anchor, check=False).strip())
            if not done_at:
                continue
            touched = set(gitutil.changed_since(self.cfg.root, done_at))
            globs, exact = self.allowed((play,))
            out.append(lambda f, g=globs, e=exact, tch=touched: f not in tch and (f in e or any(_glob(f, x) for x in g)))
        return out

    def check_scope(self, c: Check) -> None:
        """Each play stays in its write set. For the build play the ticket's areas are soft: a
        file outside them is a flag the approving review must name, not a failure (ADR-0001).
        Lead artifacts, other tickets, other plays' evidence and reviews stay hard, and so do
        the test and review plays' write sets."""
        if not self.ticket:
            if self.play == "pr":
                self._lead_scope(c)
            else:
                c.status, c.summary = "skip", "no ticket"
            return
        t = self.ticket
        globs, exact = self.allowed()
        earlier = self._earlier_play_outputs() if self.play == "build" else []
        builds = "build" in self.roles()
        own = self.cfg.rel(t.path)
        always = self.cfg.section("scope").get("always_allowed", [])
        tests = [*self.cfg.section("tests").get("globs", []), *self.cfg.section("tests").get("integration_globs", [])]
        mine = self.bookkeeping()
        bad, problems, flags = [], [], []
        for f in self.changed():
            if f == own:
                p = self._own_ticket_problems(f)
                if p:
                    problems += p
                    bad.append(f)
                continue
            if (f in mine and f in exact) or any(_glob(f, g) for g in always) or any(ok(f) for ok in earlier):
                continue
            if builds and self._split_ticket(f):
                continue
            if builds and t.type == "test" and not any(_glob(f, g) for g in tests):
                # A test ticket skips the test play, so it may not carry the code that play proves.
                problems.append(f"a test ticket changes tests only (tests.globs, tests.integration_globs): {f}")
                bad.append(f)
                continue
            if builds and f == self.cfg.data["paths"]["contracts"]:
                continue  # allowed, and it makes the lane strict (lead sign-off, contract diff)
            if self._hard(f):
                bad.append(f)  # no area, widened or not, covers these
                continue
            if f in exact or any(_glob(f, g) for g in globs):
                continue
            if builds and self._test_beside_area(f):
                continue
            if builds:
                flags.append(f)
                continue
            bad.append(f)
        named = {f for f in bad if any(p.endswith(": " + f) for p in problems)}
        c.details = problems + [f"outside {self.play} write set: {f}" for f in bad if f != own and f not in named]
        c.details += [f"out of area (the approving review must name it under ## Out of area): {f}" for f in flags]
        if self.config_note:
            c.details.append(self.config_note)
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)} file(s) outside the {self.play} play's write set. Revert them; lead "
                         f"artifacts, other tickets and other plays' files are not {t.id}'s to change")
        else:
            c.summary = f"{len(self.changed())} changed file(s), all in scope"
            if flags:
                c.summary += f"; {len(flags)} out of the ticket's areas (flagged for review)"

    def out_of_area(self) -> list[str]:
        """Files the whole ticket branch changes outside every play's write set and outside
        the hard set: the flags an approving review must name."""
        t = self.ticket
        if not t:
            return []
        globs, exact = self.allowed(PR_ROLES)
        own, contracts = self.cfg.rel(t.path), self.cfg.data["paths"]["contracts"]
        return [f for f in gitutil.changed_files(self.cfg.root, self.base)
                if f not in exact and not any(_glob(f, g) for g in globs) and f not in (own, contracts)
                and not self._test_beside_area(f) and not self._split_ticket(f) and not self._hard(f)]

    def _review_record(self, c: Check) -> None:
        """Records mode, review play: the agent's record at .sdlc-run/review-<id>.md (the runner
        publishes it) names this commit and everything the reviewer must judge."""
        t = self.ticket
        p = self.run_dir / f"review-{t.id}.md"
        if not p.is_file():
            c.status, c.summary = "fail", f"missing {self.cfg.rel(p)} (write the review record there)"
            return
        d = approval.parse(p.read_text(encoding="utf-8"))
        if d is None:
            c.status, c.summary = "fail", f"{self.cfg.rel(p)} has no approval front matter (sdlc: approval)"
            return
        problems = []
        if str(d.get("ticket", "")) != t.id:
            problems.append(f"ticket must be {t.id}")
        if str(d.get("verdict", "")) not in approval.VERDICTS:
            problems.append(f"verdict must be one of {approval.VERDICTS}")
        if str(d.get("role", "review")) not in approval.ROLES:
            problems.append(f"role must be one of {approval.ROLES}")
        if not _same_commit(str(d.get("commit", "")), gitutil.head(self.cfg.root)):
            problems.append(f"commit must be the reviewed HEAD {gitutil.head(self.cfg.root)[:12]}")
        for h in ("## Acceptance criteria", "## Findings", "## Gate"):
            if h not in {ln.strip() for ln in str(d["_body"]).split("\n")}:
                problems.append(f"missing section '{h}'")
        if d.get("verdict") == "request_changes" and not re.search(
                r"^\s*[-*]\s+\S", lint._section(str(d["_body"]), "## Findings"), re.M):
            problems.append("request_changes needs at least one finding")
        rec = approval.Record(sha=gitutil.head(self.cfg.root), who="", role=str(d.get("role", "review")),
                              verdict=str(d.get("verdict", "")), body=str(d["_body"]))
        problems += approval._content_problems(rec, rec.role, t, self.lane.name if self.lane else "standard",
                                               self.out_of_area(), self.new_amendments(), _review_entries, _glob)
        c.details = problems
        if problems:
            c.status, c.summary = "fail", f"review record invalid ({len(problems)} problem(s))"
        else:
            c.summary = f"review record valid, verdict {d.get('verdict')}; publish it with `sdlc review publish {t.id}`"

    def new_amendments(self) -> list[tuple[str, str, str]]:
        """Amendment lines this branch adds to its ticket."""
        if not self.ticket:
            return []
        old_body = ""
        if self.mb:
            old_body = fm.split(gitutil.show(self.cfg.root, self.mb, "./" + self.cfg.rel(self.ticket.path)) or "")[1]
        return tickets.new_amendments(old_body, self.ticket.body)[0]

    def _hard(self, f: str) -> bool:
        """Files no ticket PR may change, areas or not: lead artifacts, config, other tickets,
        and any evidence or review file the ticket's plays do not own."""
        p = self.cfg.data["paths"]
        # The test play's files are the red-proof's other half: the build never writes them,
        # unless the ticket has no test play because it is a test ticket (its build is that play).
        test_play_files = (self.play == "build" and not (self.ticket and self.ticket.type == "test")
                           and any(_glob(f, g) for g in self.cfg.section("tests").get("integration_globs", [])))
        return (test_play_files or any(_glob(f, g) for g in lead_write_set(self.cfg))
                or any(f.startswith(p[k].rstrip("/") + "/") for k in ("evidence", "reviews")))

    def _test_beside_area(self, f: str) -> bool:
        """A test next to an in-area file (same stem, same folder or its tests/__tests__ child)."""
        tests = self.cfg.section("tests")
        t = self.ticket
        if not tests.get("unit_beside", True):
            return False
        test_globs = tests.get("globs", [])
        if _is_test_beside(f, self.build_areas()[1], test_globs):
            return True
        if not any(_glob(f, g) for g in test_globs):
            return False
        pf = PurePosixPath(f)
        stem = re.sub(r"^test_|_test$", "", re.sub(r"(\.(test|spec))?\.[^.]+$", "", pf.name))
        dirs = [pf.parent] + ([pf.parent.parent] if pf.parent.name in ("__tests__", "tests") else [])
        for d in dirs:
            folder = self.cfg.root / d
            if not folder.is_dir():
                continue
            for src in folder.iterdir():
                rel = (d / src.name).as_posix()
                if (src.is_file() and re.sub(r"\.[^.]+$", "", src.name) == stem
                        and not any(_glob(rel, g) for g in test_globs)
                        and any(_glob(rel, g) for g in self.build_areas()[0])):
                    return True
        return False

    def _split_ticket(self, f: str) -> bool:
        """A new draft ticket this ticket split off (an amendment)."""
        p = self.cfg.data["paths"]
        if not paths.match(f, f"{p['tickets']}/T-*.md") or not (self.cfg.root / f).is_file():
            return False
        try:
            if gitutil.show(self.cfg.root, gitutil.merge_base(self.cfg.root, self.base), "./" + f) is not None:
                return False
        except gitutil.GitError:
            return False
        d = _frontmatter((self.cfg.root / f).read_text(encoding="utf-8")) or {}
        return str(d.get("split_from", "")) == self.ticket.id and str(d.get("status", "")) == "draft"

    def _own_ticket_problems(self, f: str) -> list[str]:
        """What the play changed in its own ticket. Every play may move the status along moves
        its role may make (a test agent cannot mark its ticket done). The build may also amend
        the ticket: acceptance criteria (judged by `immutable`), areas with a `widen` line,
        transforms, skills, contracts (add only), lane and risk (raise only), and new lines in
        ## Amendments. Everything else on a ticket is the lead's."""
        root, play = self.cfg.root, self.play
        ref = self.since or self.base
        try:
            ref = gitutil.merge_base(root, ref)
        except gitutil.GitError:
            pass  # a commit sha, not a branch
        p = root / f
        if not p.is_file():
            return [f"{f}: the ticket was deleted"]
        old_text = gitutil.show(root, ref, "./" + f)
        if old_text is None:
            # Created on this branch: only a mechanical ticket may be (the lane check says).
            return [] if "build" in self.roles() else [f"{f}: created by the {play} play"]
        try:
            ofm, obody, _ = fm.split(old_text)
            nfm, nbody, _ = fm.split(p.read_text(encoding="utf-8"))
            od, nd = fm.parse(ofm or ""), fm.parse(nfm or "")
        except fm.ParseError as e:
            return [f"{f}: {e}"]
        out = []
        move = (str(od.get("status", "")), str(nd.get("status", "")))
        if move[0] != move[1] and not tickets.reachable(*move, self.roles()):
            out.append(f"{f}: status {move[0]} -> {move[1]} is not a move the {play} play may make")
        changed = sorted(k for k in set(od) | set(nd) if k not in ("status", "blocked_by") and od.get(k) != nd.get(k))
        if "build" not in self.roles():
            if changed or obody.strip() != nbody.strip():
                out.append(f"{f}: only the status may change in the {play} play")
            return out
        free = {"acceptance_criteria", "areas", "files", "shared", "skills", "transforms"}
        for k in changed:
            if k in free:
                continue
            if k == "contracts" and set(_as_list(od.get(k))) <= set(_as_list(nd.get(k))):
                continue
            if k == "lane" and lanes.rank(_declared_lane(nd)) >= lanes.rank(_declared_lane(od)):
                continue
            if k == "risk" and _risk_rank(nd) >= _risk_rank(od):
                continue
            out.append(f"{f}: {k} changed; a ticket PR may amend acceptance criteria, areas, transforms, skills, "
                       f"contracts (add only) and raise lane or risk; {k} is the lead's")
        if tickets.strip_amendments(obody) != tickets.strip_amendments(nbody):
            out.append(f"{f}: the ticket body changed outside ## Amendments")
        added, problems = tickets.new_amendments(obody, nbody)
        out += [f"{f}: {x}" for x in problems]
        widened = {a[1] for a in added if a[0] == "widen"}
        for k in ("areas", "files", "shared"):
            for entry in sorted(set(_as_list(nd.get(k))) - set(_as_list(od.get(k)))):
                if entry not in widened:
                    out.append(f"{f}: {k} gains {entry} without a `- widen {entry}: <reason>` line in ## Amendments")
        return out

    def _lead_scope(self, c: Check) -> None:
        """A PR that moves no ticket is the lead's: specs, plans, contracts, tickets, config.
        Other files (a human hotfix) are reported, and fail only with scope.lead_code = "fail".
        Either way gate ci still judges the code with the base branch's config."""
        globs, _ = self.allowed()
        bad = [f for f in self.changed() if not any(_glob(f, g) for g in globs)]
        mode = str(self.cfg.section("scope").get("lead_code", "warn"))
        c.details = [f"outside the lead write set: {f}" for f in bad]
        if self.config_note:
            c.details.append(self.config_note)
        if mode not in ("warn", "fail"):
            c.status, c.summary = "fail", f"scope.lead_code must be warn or fail, got {mode!r}"
        elif bad:
            shown = ", ".join(bad[:5]) + (f" (+{len(bad) - 5} more)" if len(bad) > 5 else "")
            c.summary = (f"{len(bad)} file(s) changed without a ticket, so no ticket traces them: {shown}. "
                         "Build them through a ticket, or list lead-owned files in scope.lead_allowed")
            if mode == "fail":
                c.status = "fail"
            else:
                c.summary = "WARNING " + c.summary + " (scope.lead_code = \"warn\")"
        else:
            c.summary = f"lead PR: {len(self.changed())} changed file(s), all lead artifacts"

    def check_lane(self, c: Check) -> None:
        """Report the lane and every raise. Fail when the lane's own preconditions do not hold;
        on a PR, also when earlier evidence ran in a looser lane than the branch now needs."""
        ln, t = self.lane, self.ticket
        if not ln or not t:
            c.status, c.summary = "skip", "no ticket"
            return
        c.summary = f"lane {ln.name}" + (f" (declared {ln.declared})" if ln.name != ln.declared else "")
        c.details = list(ln.reasons) + [f"residue: {r}" for r in ln.residue[:20]]
        problems = []
        old = self.base_ticket
        if self.mb is None:
            # Without the base the diff is unknown, so no trigger can raise the lane: refuse.
            c.status, c.summary = "fail", f"no merge base with {self.base}: the lane cannot be judged"
            c.details = [f"fetch {self.base} (CI: fetch-depth 0) or pass --base"]
            return
        if ln.name != "mechanical" and t.type != "spike" and not [a for a, _ in t.acs if a]:
            problems.append(f"{t.id} has no acceptance criteria, but the {ln.name} lane proves each one: add them "
                            "(an `add AC-n` amendment), or make the diff exactly the declared transforms")
        if old is None and ln.name != "mechanical":
            problems.append(f"{t.id} was created on this branch; only a mechanical ticket whose transforms produce the "
                            "whole diff may be. Otherwise the lead makes the ticket ready on the base branch first")
        if ln.name == "mechanical" and self.play == "test":
            problems.append("the mechanical lane has no test play: the build gate's full suite is its proof")
        if ln.name == "strict" and not self.records and not str((old or {}).get("accepted_by", "") or "").strip():
            problems.append(f"the strict lane needs lead sign-off: accepted_by on {self.base}'s version of {t.id} "
                            "(set in a lead PR)")
        if self.play == "pr" and not self.records:
            for play in EVIDENCE_PLAYS:
                ev = self.cfg.path("evidence") / f"{t.id}.{play}.json"
                if not ev.is_file():
                    continue
                ran = json.loads(ev.read_text(encoding="utf-8")).get("lane") or "standard"
                if lanes.rank(ran) < lanes.rank(ln.name):
                    problems.append(f"{play} evidence ran in the {ran} lane, but this branch needs {ln.name}: "
                                    f"re-run `sdlc gate {play} {t.id}`")
        if problems:
            c.status = "fail"
            c.details = problems + c.details
            c.summary += f": {len(problems)} problem(s)"

    def check_mechanical(self, c: Check) -> None:
        """The diff is exactly the declared transforms, in production code and tests alike."""
        ln = self.lane
        if not ln or ln.name != "mechanical":
            c.status, c.summary = "skip", "not in the mechanical lane"
            return
        if ln.residue:  # resolve() raises such a PR to standard; never pass it here either
            c.status, c.summary, c.details = "fail", f"{len(ln.residue)} change(s) beyond the transforms", ln.residue
            return
        n = len(lanes.parse_transforms(self.ticket.transforms)[0])
        c.summary = f"the diff is exactly {n} declared transform(s); review judges the transform list"
        c.details = list(self.ticket.transforms)

    def check_contract_diff(self, c: Check) -> None:
        """Strict lane: what changed in CONTRACTS since the merge base, key by key. Every changed
        key must be cited in the ticket's contracts:; removed keys are breaking."""
        t = self.ticket
        rel = self.cfg.data["paths"]["contracts"]
        try:
            mb = gitutil.merge_base(self.cfg.root, self.base)
        except gitutil.GitError as e:
            c.status, c.summary = "fail", str(e)
            return
        from .artifacts import parse_contracts

        before = parse_contracts(self.cfg.path("contracts"), self.cfg,
                                 text=gitutil.show(self.cfg.root, mb, "./" + rel) or "")
        after = self.repo.contracts
        old, new = _contract_keys(before), _contract_keys(after)
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        modified = sorted(k for k in set(old) & set(new) if old[k] != new[k])
        refs = t.contracts if t else []
        cited = {extract_key(r) for r in refs} | {r.strip() for r in refs}
        base_refs = _as_list((self.base_ticket or {}).get("contracts"))
        cited_before = {extract_key(r) for r in base_refs} | {r.strip() for r in base_refs}
        details = [f"added: {k}" for k in added]
        for k in modified:
            gone = _dropped(old[k], new[k])
            details.append(f"narrowed (breaking): {k}: dropped {' '.join(gone[:8])}" if gone else f"changed: {k}")
        details += [f"removed (breaking): {k}" for k in removed]
        prose = _contract_prose(before) != _contract_prose(after)
        if prose:
            details.append(f"{rel} changed outside every declared key (conventions or prose): review the raw diff")
        uncited = [k for k in added + modified + removed if _contract_ref(k) not in cited]
        details += [f"{k} changed, but {t.id if t else 'the ticket'} does not cite {_contract_ref(k)} in contracts:"
                    for k in uncited]
        # A strict build may cite a key in the same PR that changes it; say so, for the lead.
        details += [f"{_contract_ref(k)} is cited by this branch, not by {self.base}'s ticket"
                    for k in added + modified + removed if k not in uncited and _contract_ref(k) not in cited_before]
        c.details = details
        if uncited:
            c.status, c.summary = "fail", f"{len(uncited)} changed contract key(s) the ticket does not cite"
        elif added or removed or modified or prose:
            c.summary = (f"{len(added)} added, {len(modified)} changed, {len(removed)} removed contract key(s), all "
                         f"cited" + ("; prose outside the keys changed" if prose else ""))
        else:
            c.summary = f"{rel} unchanged since {self.base}"

    def check_spike(self, c: Check) -> None:
        """A spike delivers findings: a file in its areas with a heading per question. It may
        not change production code or tests, in its areas or out of them."""
        t = self.ticket
        if not t or t.type != "spike":
            c.status, c.summary = "skip", "not a spike"
            return
        qs = [q for q, _ in t.questions if q]
        # Only documents, and only in the areas the lead gave the spike: widening them in the
        # PR, or leaving source_globs unset, must not let a spike ship code.
        areas, _ = self.build_areas()
        bad, findings = [], []
        for f in self.changed():
            if f in self.bookkeeping() or self._split_ticket(f):
                continue
            if PurePosixPath(f).suffix.lower() not in SPIKE_DOCS:
                bad.append(f"{f}: a spike changes documents only ({', '.join(SPIKE_DOCS)}), not code, tests or config")
            elif not any(_glob(f, g) for g in areas):
                bad.append(f"{f}: outside the spike's areas")
            elif (self.cfg.root / f).is_file():
                findings.append(f)
        headings = set()
        for f in findings:
            for ln in (self.cfg.root / f).read_text(encoding="utf-8", errors="replace").splitlines():
                if m := re.match(r"^#+\s+(Q-\d+)\b", ln):
                    headings.add(m.group(1))
        unanswered = [q for q in qs if q not in headings]
        c.details = bad + [f"{q}: no findings heading starts with {q}" for q in unanswered]
        if not qs:
            c.status, c.summary = "fail", "a spike needs questions: (Q-n: ...)"
        elif bad or unanswered:
            c.status, c.summary = "fail", f"{len(bad)} disallowed change(s), {len(unanswered)} unanswered question(s)"
        else:
            c.summary = f"{len(qs)} question(s) answered in {len(findings)} findings file(s)"

    def check_contracts(self, c: Check) -> None:
        contracts = self.repo.contracts
        declared = {r.key for r in contracts.routes}
        code, code_pages, errs = extract.code_surface(self.cfg)
        details = list(errs)
        if errs and not code:
            c.status, c.summary, c.details = "fail", "cannot extract routes from code", details
            return
        undeclared = sorted(set(code) - declared)
        for k in undeclared:
            details.append(f"route in code but not in CONTRACTS: {k} ({code[k]})")
        declared_pages = {normalize_path(p) for p in contracts.pages}
        for pg in sorted(set(code_pages) - declared_pages):
            details.append(f"page in code but not in CONTRACTS: {pg} ({code_pages[pg]})")
        tables = extract.code_tables(self.cfg)
        for name in sorted(set(tables) - set(contracts.tables)):
            details.append(f"table in code but not in CONTRACTS: {name} ({tables[name]})")
        if self.ticket:
            mine = {extract_key(r) for r in self.ticket.contracts}
            for k in sorted(mine & declared):
                if k not in code and self.play in ("build", "test", "ci"):
                    details.append(f"{self.ticket.id} owns {k} but no handler exists")
        paths = {r.path for r in contracts.routes}
        built = {k.split(" ", 1)[1] for k in code}
        for f, ln, p in extract.client_calls(self.cfg):
            if not extract.path_matches(p, paths):
                details.append(f"client calls {p} at {f}:{ln}, which no contract route serves")
            elif not extract.path_matches(p, built):
                # Matching the contract is not enough: the call fails unless a route serves it.
                details.append(f"client calls {p} at {f}:{ln}; CONTRACTS declares it, but no built route serves it")
        unimpl = sorted(declared - set(code))
        c.details = details
        if details:
            c.status = "fail"
            c.summary = f"{len(details)} contract drift problem(s)"
        else:
            c.summary = (f"{len(code)} code route(s) match CONTRACTS; "
                         f"{len(unimpl)} declared route(s) not built yet")

    def _command(self, c: Check) -> None:
        cmd = self.cfg.commands.get(c.name, "")
        optional = c.name in self.cfg.section("gate").get("optional", [])
        if self.lane and self.lane.name == "strict" and c.name in real_stack_suites(self.cfg):
            optional = False  # the strict lane always runs the real stack
        if not cmd:
            c.status = "skip" if optional else "fail"
            c.summary = f"commands.{c.name} not configured" + ("" if optional else " (required for this play)")
            return
        junit = self.run_dir / f"junit-{c.name}.xml"
        if junit.exists():
            junit.unlink()
        # Commands run at the root: a root-relative path survives a root with spaces in it
        # (an unquoted absolute path splits into two arguments) and reads the same in evidence.
        shown = cmd.replace("{junit}", self.cfg.rel(junit)).replace("{port}", str(self.cfg.section("app")["port"]))
        code, log = self._shell(c.name, shown)
        c.log = self.cfg.rel(log)
        tail = _tail(log, 40)
        if code != 0:
            c.status, c.summary, c.details = "fail", f"`{shown}` exited {code}", tail
            if c.name in JUNIT_CHECKS and "{junit}" in cmd and junit.is_file():
                self.junit_used[c.name] = self._read_junit(c.name, junit) > 0
            return
        c.summary = f"`{shown}` ok"
        if c.name in JUNIT_CHECKS:
            if "{junit}" not in cmd:
                self.junit_used[c.name] = False
                c.details.append("command has no {junit} placeholder: AC coverage cannot be proven")
                return
            if not junit.is_file():
                c.status, c.summary = "fail", f"{c.name} produced no JUnit report at {junit.name}"
                return
            n = self._read_junit(c.name, junit)
            self.junit_used[c.name] = True
            if n == 0:
                c.status, c.summary = "fail", f"{c.name} ran 0 tests"
            else:
                c.summary += f" ({n} tests)"

    def _read_junit(self, source: str, path: Path, into: list[TestCase] | None = None) -> int:
        into = self.testcases if into is None else into
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return 0
        n = 0
        for tc in root.iter("testcase"):
            n += 1
            name = f"{tc.get('classname', '')} {tc.get('name', '')}".strip()
            if tc.find("failure") is not None or tc.find("error") is not None:
                st = "failed"
            elif tc.find("skipped") is not None:
                st = "skipped"
            else:
                st = "passed"
            into.append(TestCase(name, st, source))
        return n

    def ac_matrix(self, ticket: Ticket | None = None) -> dict:
        ticket = ticket or self.ticket
        if not ticket:
            return {}
        out = {}
        for tag in ticket.ac_tags():
            pat = re.compile(re.escape(tag) + r"(?!\d)")
            hits = [tc for tc in self.testcases if pat.search(tc.name)]
            st = ("missing" if not hits else "failed" if any(h.status == "failed" for h in hits)
                  else "passed" if any(h.status == "passed" for h in hits) else "skipped")
            out[tag] = {"status": st, "tests": [f"[{h.source}] {h.name}" for h in hits][:10]}
        return out

    def check_ac_coverage(self, c: Check) -> None:
        # A ticket play proves its own AC. Without a ticket (gate ci) every shipped ticket's
        # AC must still be proven, so a later change that deletes or breaks those tests fails.
        shipped = [t for _, t in sorted(self.repo.tickets.items())
                   if (self.repo.status_of(t) == "done" if self.records else t.status in ("in_review", "done"))]
        # The mechanical lane proves nothing new; it proves every shipped AC still holds.
        whole = not self.ticket or bool(self.lane and self.lane.name == "mechanical")
        targets = [self.ticket] if not whole else [t for t in shipped if not self.ticket or t.id != self.ticket.id]
        if not targets:
            c.status, c.summary = "skip", "no ticket in review or done"
            return
        if not any(self.junit_used.values()):
            c.status = "fail"
            c.summary = "no test command wrote JUnit ({junit}); AC coverage cannot be proven"
            return
        matrix: dict = {}
        for t in targets:
            matrix.update(self.ac_matrix(t))
        bad = {k: v for k, v in matrix.items() if v["status"] != "passed"}
        c.details = [f"{k}: {v['status']}" for k, v in matrix.items() if not whole or v["status"] != "passed"]
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)}/{len(matrix)} AC without a passing test. Name tests with the tag, e.g. "
                         f"it('{next(iter(bad))} ...')")
        else:
            c.summary = f"all {len(matrix)} AC of {len(targets)} ticket(s) proven by passing tests"
        suites = real_stack_suites(self.cfg)
        names = "/".join(suites)
        proving = self.play == "test" or (self.play == "pr" and self.records) or (
            self.play == "build" and self.ticket is not None and self.ticket.type == "test")
        if proving and self.ticket and suites and self.ticket.real_stack_proof and not whole:
            # The test play exists to prove AC through the real stack; unit proof alone is the
            # build's. A test ticket's build is its test play, so it carries the same proof.
            if not self._real_stack_proof(self.ticket.id):
                c.status = "fail"
                who = "the test ticket's build" if self.ticket.type == "test" else "the test play"
                c.summary = (f"no passing {names} test carries a {self.ticket.id}/AC-n tag; "
                             f"{who} must prove AC through the real stack")
        elif whole and suites:
            # Approval needs test evidence, but evidence is a file the ticket PR wrote. CI
            # re-proves what it claims: every done ticket has a passing real-stack test.
            unproven = [t.id for t in targets
                        if t.status == "done" and t.real_stack_proof and not self._real_stack_proof(t.id)]
            if unproven:
                c.status = "fail"
                c.details += [f"{tid}: done, but no passing {names} test carries its tag" for tid in unproven]
                c.summary = (f"{len(unproven)} done ticket(s) without real-stack proof: {', '.join(unproven)}; "
                             "run their test play")

    def _real_stack_proof(self, tid: str) -> bool:
        """A passing real-stack test carries one of the AC tags the ticket declares (an AC-99
        the ticket does not have proves none of its AC)."""
        t = self.repo.tickets.get(tid)
        tags = t.ac_tags() if t else []
        if not tags:
            return False
        tag = re.compile("(?:" + "|".join(re.escape(x) for x in tags) + r")(?!\d)")
        suites = real_stack_suites(self.cfg)
        return any(tc.source in suites and tc.status == "passed" and tag.search(tc.name) for tc in self.testcases)

    def check_ac_red(self, c: Check) -> None:
        """Each AC needs a tagged test that fails without the ticket's code. The unit command
        runs again with the ticket's production files put back to the base branch; an AC
        whose tagged tests all still pass is proven by tests that do not depend on the work
        (`expect(true)`, asserting on a fixture, re-testing old behaviour)."""
        t = self.ticket
        cmd = self.cfg.commands.get("unit", "")
        if not t or not cmd or "{junit}" not in cmd:
            c.status, c.summary = "skip", "needs a ticket and a unit command with {junit} (ac-coverage reports that)"
            return
        tests = self.cfg.section("tests")
        test_globs = tests.get("globs", [])
        # Production source the branch changed: [tests] source_globs, else the ticket's areas and
        # shared globs. Manifests, lockfiles and config are not reverted (they break the install
        # or build and fail ac-red for the wrong reason); review judges them.
        scope = tests.get("source_globs", []) or (t.areas + t.shared)
        prod = sorted(f for f in set(self.changed()) | set(t.files)
                      if any(_glob(f, g) for g in scope) and not any(_glob(f, g) for g in test_globs))
        mb = gitutil.merge_base(self.cfg.root, self.base)
        prod = [f for f in prod if _norm(gitutil.show_bytes(self.cfg.root, mb, "./" + f)) != _read_or_none(self.cfg.root / f)]
        if not prod:
            c.status, c.summary = "skip", f"no production file of {t.id} differs from {self.base}; nothing to revert"
            return
        backup = self.run_dir / RED_BACKUP
        cases: list[TestCase] = []
        backup.mkdir(parents=True)
        try:
            manifest = {}
            for f in prod:
                p = self.cfg.root / f
                if p.is_file():
                    (backup / str(len(manifest))).write_bytes(p.read_bytes())
                    manifest[f] = str(len(manifest))
                else:
                    manifest[f] = None
                (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                old = gitutil.show_bytes(self.cfg.root, mb, "./" + f)
                if old is None and p.is_file():
                    # Empty, not deleted: a test file importing a module the ticket created
                    # would otherwise fail at import as a whole, and a tautology in it would
                    # count as red. Imports of an empty module resolve (to undefined/attribute
                    # errors), so each test passes or fails on its own assertions.
                    p.write_bytes(b"")
                elif old is not None:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(old)
            junit = self.run_dir / "junit-ac-red.xml"
            junit.unlink(missing_ok=True)
            code, log = self._shell("ac-red", cmd.replace("{junit}", self.cfg.rel(junit))
                                    .replace("{port}", str(self.cfg.section("app")["port"])))
            c.log = self.cfg.rel(log)
            self._read_junit("ac-red", junit, into=cases)
        finally:
            _restore_red_backup(self.cfg.root, backup)
        green, unknown = [], []
        for tag in t.ac_tags():
            pat = re.compile(re.escape(tag) + r"(?!\d)")
            hits = [tc for tc in cases if pat.search(tc.name)]
            if hits and all(h.status == "passed" for h in hits):
                green.append(f"{tag}: passes without this ticket's code ({'; '.join(h.name for h in hits[:3])})")
            elif not hits:
                unknown.append(f"{tag}: its tests did not run without the ticket's code (whole file failed to "
                               "load?); not proven red, not counted against it")
        c.details = green + unknown
        if green:
            c.status = "fail"
            c.summary = (f"{len(green)} AC proven only by tests that pass with {', '.join(prod) or 'nothing'} "
                         f"reverted to {self.base}; assert on what this ticket built")
        elif unknown:
            c.summary = (f"no AC passes without the ticket's code; {len(unknown)} AC could not be checked "
                         f"({len(prod)} file(s) reverted)")
        else:
            c.summary = f"every AC has a test that fails without the ticket's code ({len(prod)} file(s) reverted)"

    def check_test_quality(self, c: Check) -> None:
        tests = self.cfg.section("tests")
        globs = tests.get("globs", [])
        if not globs:
            c.status, c.summary = "fail", "tests.globs not configured"
            return
        rules = BUILTIN_TEST_FORBID + list(tests.get("forbid", []))
        if self.play == "ci" or not self.ticket:
            files = paths.glob_files(self.cfg.root, globs)
        else:
            files = [f for f in self.changed() if any(_glob(f, g) for g in globs)]
        problems = []
        for f in files:
            p = self.cfg.root / f
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for rule in rules:
                for m in re.finditer(rule["regex"], text, re.M):
                    ln = text.count("\n", 0, m.start()) + 1
                    problems.append(f"{f}:{ln}: {rule['message']}")
        c.details = problems
        if problems:
            c.status, c.summary = "fail", f"{len(problems)} test-quality problem(s)"
        else:
            c.summary = f"{len(files)} test file(s) clean"

    def check_smoke(self, c: Check) -> None:
        cmd = self.cfg.commands.get("start", "")
        contracts = self.repo.contracts
        code, _ = extract.code_routes(self.cfg)
        routes = [r for r in contracts.routes if r.key in code]
        # A page is probed once its owner ticket is being built or has shipped.
        live = {"in_progress", "in_review", "done"}
        pages = [pg for pg in contracts.pages
                 if not (owner := contracts.page_attrs.get(pg, {}).get("owner"))
                 or (self.ticket is not None and owner == self.ticket.id)
                 or (owner in self.repo.tickets and self.repo.status_of(self.repo.tickets[owner]) in live)]
        if not cmd:
            c.status, c.summary = "fail", "commands.start not configured; the app was never started"
            return
        app = self.cfg.section("app")
        port, host = int(app["port"]), app["host"]
        if _port_open(host, port):
            c.status, c.summary = "fail", f"port {port} is already in use; stop that process or set app.port"
            return
        base_url = f"http://{host}:{port}"
        log = self.run_dir / "logs" / "smoke-server.log"
        env = dict(os.environ, PORT=str(port))
        rendered = cmd.replace("{port}", str(port)).replace("{base_url}", base_url)
        with open(log, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(rendered, shell=True, cwd=self.cfg.root, stdout=lf,
                                    stderr=subprocess.STDOUT, env=env,
                                    **_new_group())
        c.log = self.cfg.rel(log)
        try:
            deadline = time.monotonic() + int(app["ready_timeout"])
            ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                st, _, _ = _http(base_url + app["ready_path"], "GET")
                if st is not None and st < 500:
                    ready = True
                    break
                time.sleep(1)
            if not ready:
                c.status, c.summary = "fail", f"server not ready on {base_url}{app['ready_path']}"
                c.details = _tail(log, 40)
                return
            problems, ok = [], 0
            if code and not routes:
                # Probing nothing is not a pass: the routes the app serves sit at paths the
                # contract does not declare (wrong prefix, renamed resource).
                problems.append(f"the app serves {len(code)} route(s), none at a CONTRACTS path, "
                                "so no route was probed")
            missing_status = set(app.get("missing_status", [405]))
            json_ct = app.get("app_404_content_type", "application/json")
            for r in routes:
                url = base_url + _sample_path(r.attrs.get("sample") or r.attrs.get("raw_path", r.path))
                if r.method not in ("GET", "HEAD") and app.get("mutating_probe", "request") == "options":
                    # Ask the router which methods it serves instead of sending a write.
                    st, allow = _options(url)
                    if st is not None and 200 <= st < 300 and r.method in allow:
                        ok += 1
                    else:
                        problems.append(f"{r.key}: OPTIONS answered {st} with Allow: {', '.join(sorted(allow)) or '-'} "
                                        f"-> the router does not serve {r.method} here")
                    continue
                st, ctype, body = _http(url, r.method)
                if st is None:
                    problems.append(f"{r.key}: no response ({body})")
                elif st in missing_status or (st == 404 and json_ct not in (ctype or "")):
                    problems.append(f"{r.key}: {st} {ctype or ''} -> the router does not serve this route")
                elif st >= 500:
                    problems.append(f"{r.key}: {st} server error on an unauthenticated probe")
                else:
                    ok += 1
            for pg in pages:
                st, ctype, body = _http(base_url + _sample_path(contracts.page_attrs.get(pg, {}).get("sample", pg)), "GET")
                if st is None or st >= 400:
                    problems.append(f"page {pg}: {st} {body[:120] if body else ''}")
                else:
                    ok += 1
            c.details = problems
            if problems:
                probes = len(routes) + len(pages)
                c.status, c.summary = "fail", (f"{len(problems)} of {probes} probe(s) failed" if probes
                                               else "no contract route or page was probed")
            else:
                c.summary = f"app booted; {ok} route/page probe(s) answered"
        finally:
            _kill(proc)

    def check_immutable(self, c: Check) -> None:
        """Accepted ADRs never change; acceptance criteria only change with their spec."""
        cfg = self.cfg
        mb = self.since or gitutil.merge_base(cfg.root, self.base)
        changed = set(self.changed())
        adr_dir = cfg.data["paths"]["decisions"]
        tdir = cfg.data["paths"]["tickets"]
        problems = []
        for f in sorted(changed):
            if paths.match(f, f"{adr_dir}/ADR-*.md"):
                old = _frontmatter(gitutil.show(cfg.root, mb, "./" + f))
                if old is not None and old.get("status") == "accepted":
                    problems.append(f"{f}: accepted ADR edited; write a new ADR that supersedes it")
            elif paths.match(f, f"{tdir}/T-*.md") and not (cfg.root / f).exists():
                old = _frontmatter(gitutil.show(cfg.root, mb, "./" + f))
                if old is not None and old.get("status") not in ("draft", None):
                    problems.append(f"{f}: {old.get('status')} ticket deleted; supersede it with a new ticket instead")
        reqs_now = {r: v.text for r, v in self.repo.requirements().items()}
        lead_only: list[str] = []
        for t in self.repo.tickets.values():
            rel = cfg.rel(t.path)
            if rel not in changed:
                continue
            old = _frontmatter(gitutil.show(cfg.root, mb, "./" + rel))
            if old is None or old.get("status") in ("draft", None):
                continue  # AC are not accepted until the lead makes the ticket ready
            old_acs = dict(_acs(old))
            new_acs = dict(t.acs)
            # An AC may change together with a requirement it serves (the spec decides), or
            # through an amendment the reviewer judges: add, strengthen, or split it verbatim
            # into a follow-up. Weakening or removing one still needs the spec.
            cited = [str(r) for r in (old.get("requirements") or [])]
            spec = str(old.get("source_spec", ""))
            reqs_then = _requirements_at(cfg, mb, spec)
            moved = [r for r in cited if reqs_then.get(r) != reqs_now.get(r)]
            old_body = fm.split(gitutil.show(cfg.root, mb, "./" + rel) or "")[1]
            added, amend_problems = tickets.new_amendments(old_body, t.body)
            problems += [f"{rel}: {x}" for x in amend_problems]
            by_kind: dict[str, set[str]] = {}
            for kind, target, _ in added:
                by_kind.setdefault(kind, set()).add(target)
            for ac, text in old_acs.items():
                if not ac or new_acs.get(ac) == text or moved:
                    continue
                if ac in new_acs and ac in by_kind.get("strengthen", set()):
                    continue
                if ac not in new_acs and self._split_off(t, ac, text, by_kind.get("split", set())):
                    continue
                if self.records and ac in by_kind.get("weaken" if ac in new_acs else "remove", set()):
                    # Allowed here; `sdlc approval` then requires a lead's approval of the head.
                    lead_only.append(f"{rel}: {ac} {'weakened' if ac in new_acs else 'removed'} by amendment: "
                                     "needs a lead approval")
                    continue
                what = "removed" if ac not in new_acs else "reworded"
                hint = ("an amendment: `- split AC-n -> T-id: why` with the AC verbatim in a new draft ticket"
                        if what == "removed" else "a `- strengthen AC-n: why` amendment the reviewer judges")
                problems.append(f"{rel}: {ac} {what}, but none of its requirements ({', '.join(cited) or 'none'}) "
                                f"changed in {spec or 'its source_spec'} and there is no {hint}. Weakening or "
                                "removing an AC needs the spec")
            # `sdlc migrate` numbering a v0 criterion ("- text" -> "AC-n: text") adds nothing.
            unnumbered = {str(x).strip() for x in old.get("acceptance_criteria") or []
                          if not AC_RE.match(str(x).strip())}
            for ac, text in new_acs.items():
                if (ac and ac not in old_acs and not moved and text not in unnumbered
                        and ac not in by_kind.get("add", set())):
                    problems.append(f"{rel}: {ac} added without an `- add {ac}: why` amendment")
        problems += self._baseline_growth(mb, changed)
        c.details = problems + lead_only
        if problems:
            c.status, c.summary = "fail", f"{len(problems)} immutable artifact(s) changed"
        elif lead_only:
            c.summary = (f"{len(lead_only)} AC weakened or removed by amendment: allowed only with a lead "
                         "approval (`sdlc approval` requires it)")
        else:
            c.summary = "no accepted ADR edited, no AC weakened, baseline not grown"

    def _split_off(self, t: Ticket, ac: str, text: str, splits: set[str]) -> bool:
        """`split AC-n -> T-id`: the AC moved verbatim into a draft ticket split from `t`."""
        for target in splits:
            m = re.fullmatch(r"(AC-\d+)\s*->\s*(T-\d+-\d+)", target)
            if not m or m.group(1) != ac:
                continue
            other = self.repo.tickets.get(m.group(2))
            if (other is not None and str(other.data.get("split_from", "")) == t.id
                    and text in {x for _, x in other.acs}):
                return True
        return False

    def _baseline_growth(self, mb: str, changed: set[str]) -> list[str]:
        """sdlc-baseline.json only shrinks: a change may drop entries, never add one, or a
        branch could baseline its own new failure. Only the lead creates it, once."""
        rel = self.baseline_rel
        if rel not in changed:
            return []
        # Both sides with paths renamed up to HEAD, so a moved file's entries compare equal.
        branch = baseline.load(self.cfg.root, rel)
        before = baseline.load_at(self.cfg.root, mb, rel)
        if before is None:
            if self.ticket:
                return [f"{rel}: created by a ticket; only the lead adds the baseline (`sdlc baseline` in a lead PR)"]
            return []
        return [f"{rel}: may only shrink, but adds {e}" for e in baseline.grown(before, branch)]

    def check_skills(self, c: Check) -> None:
        from . import skills

        problems = skills.verify(self.cfg)
        c.details = problems
        if problems:
            c.status, c.summary = "fail", f"{len(problems)} skill lock problem(s)"
        else:
            c.summary = "vendored skills match skills.lock.json"

    def check_review_file(self, c: Check) -> None:
        if not self.ticket:
            if self.play == "pr":
                c.status, c.summary = "skip", "lead PR: no ticket to review"
            else:
                c.status, c.summary = "fail", "review needs a ticket"
            return
        if self.records:
            self._review_record(c)
            return
        p = self.cfg.path("reviews") / f"{self.ticket.id}.md"
        if self.play == "pr" and self.ticket.status != "done":
            # Review happens before the PR: a PR carries a reviewed, done ticket, so it arrives
            # complete and merges on green instead of iterating in review threads.
            c.status = "fail"
            c.summary = (f"{self.ticket.id} is {self.ticket.status}: open the PR after review "
                         f"(an approving {self.cfg.rel(p)}, then `sdlc status {self.ticket.id} done --as merge`)")
            return
        if not p.is_file():
            c.status, c.summary = "fail", f"missing {self.cfg.rel(p)}"
            return
        issues = lint.lint_review_file(self.repo, p)
        c.details = [str(i) for i in issues]
        data, body = fm.load(p)
        ev_problems = _evidence_problems(self.cfg, self.ticket, str(data.get("commit", "")))
        if data.get("verdict") == "approve" and not ev_problems:
            ev_problems = _changed_after_review(self.cfg, self.ticket, str(data.get("commit", "")), self.base)
        if data.get("verdict") == "approve":
            # Areas are soft: the reviewer, not the gate, accepts each file outside them.
            named = _review_entries(body, "## Out of area")
            ev_problems += [f"out of area and not named under ## Out of area in {self.cfg.rel(p)}: {f}"
                            for f in self.out_of_area() if not any(f == e or _glob(f, e) for e in named)]
            # Amendments the reviewer judges (ADR-0001): each must be named under ## Amendments.
            judged = set(_review_entries(body, "## Amendments"))
            for kind, target, _ in self.new_amendments():
                key = target.split()[0]
                if kind in ("strengthen", "split", "widen") and key not in judged:
                    ev_problems.append(f"amendment `{kind} {target}` is not named under ## Amendments in "
                                       f"{self.cfg.rel(p)}; the reviewer judges each one")
        c.details += ev_problems
        if data.get("verdict") == "approve" and ev_problems:
            c.status, c.summary = "fail", "approve without passing evidence for the reviewed commit"
        elif any(i.level == "error" for i in issues):
            c.status, c.summary = "fail", "review file invalid"
        else:
            c.summary = f"review valid, verdict {data.get('verdict')}"

    # -- helpers ----------------------------------------------------------
    def _shell(self, name: str, cmd: str) -> tuple[int, Path]:
        log = self.run_dir / "logs" / f"{name}.log"
        timeout = int(self.cfg.section("gate").get("timeout", 1800))
        with open(log, "w", encoding="utf-8") as lf:
            lf.write(f"$ {cmd}\n")
            lf.flush()
            try:
                env = dict(os.environ, CI=os.environ.get("CI", "1"), NO_COLOR="1", FORCE_COLOR="0")
                r = subprocess.run(cmd, shell=True, cwd=self.cfg.root, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=timeout, env=env)
                code = r.returncode
            except subprocess.TimeoutExpired:
                lf.write(f"\n[sdlc] timed out after {timeout}s\n")
                code = 124
        return code, log


def _frontmatter(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        head, _, _ = fm.split(text)
        return fm.parse(head or "")
    except fm.ParseError:
        return {}


def _requirements_at(cfg: Config, ref: str, spec: str) -> dict[str, str]:
    from .artifacts import REQ_DEF_RE

    text = gitutil.show(cfg.root, ref, "./" + spec) if spec else None
    out = {}
    for line in (fm.split(text)[1] if text else "").split("\n"):
        m = REQ_DEF_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _acs(data: dict) -> list[tuple[str, str]]:
    from .artifacts import AC_RE

    out = []
    for raw in data.get("acceptance_criteria") or []:
        m = AC_RE.match(str(raw).strip())
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def lead_write_set(cfg: Config) -> list[str]:
    """Globs a PR that moves no ticket may change: the lead plays' artifacts, the kit's
    config and generated entry files, and whatever scope.lead_allowed adds."""
    from . import adapters

    p = cfg.data["paths"]
    out = [f"{p[k]}/**" for k in ("intent", "design", "arch", "decisions", "tickets", "ops", "skills")]
    out += [p["contracts"], p["skills_lock"], p.get("baseline", "sdlc-baseline.json"),
            p.get("waivers", waivers.DEFAULT_PATH), config.CONFIG_NAME,
            "AGENTS.md", *adapters.files(cfg),
            ".sdlc", ".sdlc/**", ".github/workflows/**"]  # the kit pin and CI that runs the gate
    return out + list(cfg.section("scope").get("lead_allowed", []))


def real_stack_suites(cfg: Config) -> list[str]:
    """Test suites whose tagged tests prove a ticket through the real stack (tests.real_stack)."""
    return [s for s in cfg.section("tests").get("real_stack", ["integration", "e2e"]) if s in ("integration", "e2e")]


def pr_tickets(cfg: Config, base: str) -> list[str]:
    """Tickets a branch moves: in progress or later, with their ticket, evidence or review
    file changed against the base. `gate pr` without an id judges the one it finds."""
    repo = Repo(cfg)
    if approval.records_mode(cfg):
        # Status is derived: a PR serves the tickets its commits name in Sdlc-Ticket trailers.
        try:
            mb = gitutil.merge_base(cfg.root, base)
        except gitutil.GitError:
            return []
        named = gitutil.trailer_values(cfg.root, f"{mb}..HEAD", "Sdlc-Ticket")
        return sorted({t for t in named if t in repo.tickets})
    p = cfg.data["paths"]
    dirs = (p["tickets"], p["evidence"], p["reviews"])
    ids = set()
    mb = None
    for f in gitutil.changed_files(cfg.root, base):
        m = re.search(r"(?:^|/)(T-\d+-\d+)[^/]*$", f)
        if m and any(f.startswith(d.rstrip("/") + "/") for d in dirs):
            if f.startswith(p["tickets"].rstrip("/") + "/") and (cfg.root / f).is_file():
                # `sdlc migrate` (numbering the AC, marking legacy: v0) is a lead change, not a move.
                mb = mb or gitutil.merge_base(cfg.root, base)
                old = (gitutil.show(cfg.root, mb, "./" + f) or "").replace("\r\n", "\n")
                new = (cfg.root / f).read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
                numbered = tickets.migrate_acs_text(old, f)[0] if old else ""
                if old and old != new and new in (numbered, tickets.mark_legacy_text(numbered)):
                    continue
            ids.add(m.group(1))
    live = ("in_progress", "in_review", "done")
    return sorted(i for i in ids if i in repo.tickets and repo.tickets[i].status in live)


def proven_commit(cfg: Config, tid: str, plays: tuple[str, ...]) -> str | None:
    """Commit of the first passing evidence found among `plays` (latest play first)."""
    for play in plays:
        p = cfg.path("evidence") / f"{tid}.{play}.json"
        if p.is_file():
            ev = json.loads(p.read_text(encoding="utf-8"))
            if ev.get("result") == "pass" and ev.get("commit") and not ev.get("partial"):
                return ev["commit"]
    return None


def _play_commit(cfg: Config, base: str, plays: tuple[str, ...]) -> str | None:
    """The newest commit on the branch a play made (its Sdlc-Play trailer): where the next play
    starts when evidence is not committed."""
    try:
        mb = gitutil.merge_base(cfg.root, base)
    except gitutil.GitError:
        return None
    # Repeated trailers are joined with US (0x1f), which no value contains: a comma inside one
    # value ("other, build") is part of that value, not a second play.
    log = gitutil.git(cfg.root, "log", f"{mb}..HEAD", "--format=%H %(trailers:key=Sdlc-Play,valueonly,separator=%x1F)",
                      check=False)
    for line in log.splitlines():
        sha, _, play = line.partition(" ")
        if any(v.strip() in plays for v in play.split("\x1f")):  # a commit may carry several
            return sha
    return None


def _evidence_commit(cfg: Config, tid: str, plays: tuple[str, ...]) -> str | None:
    """The last commit that committed evidence for `plays` (where the next play starts)."""
    rels = [cfg.rel(cfg.path("evidence") / f"{tid}.{p}.json") for p in plays]
    out = gitutil.git(cfg.root, "log", "-1", "--format=%H", "--", *rels, check=False).strip()
    return out or proven_commit(cfg, tid, tuple(reversed(plays)))


def extract_key(ref: str) -> str:
    from .artifacts import normalize_route_key

    return normalize_route_key(ref.split("#", 1)[-1])


def _evidence_problems(cfg: Config, t: Ticket, commit: str) -> list[str]:
    """Problems with approving `commit`: build (and test, when the product has integration or
    e2e tests) must have passed on a clean tree, and the review must name the commit the
    latest of them proved."""
    out: list[str] = []
    proven: dict[str, str] = {}
    # Unit tests run on stubs; the test play is the only proof through the real stack, so a
    # product that has one cannot skip it (gate test fails without a tagged integration test).
    # A lead may mark a ticket `test: none` (lint refuses it for tickets serving routes/pages).
    build_ev = cfg.path("evidence") / f"{t.id}.build.json"
    mechanical = build_ev.is_file() and json.loads(build_ev.read_text(encoding="utf-8")).get("lane") == "mechanical"
    # A mechanical build has no test play: its full suite is the proof (gate pr re-checks the lane).
    suites = real_stack_suites(cfg) if t.test_play and not mechanical else []
    real_stack = [k for k in suites if cfg.commands.get(k)]
    if suites and not real_stack:
        out.append(f"no real-stack suite is configured (tests.real_stack: {', '.join(suites)}): nothing can prove "
                   f"{t.id} through the real stack; configure one, or the lead sets tests.real_stack = [] "
                   "to accept unit-only proof")
    for play in EVIDENCE_PLAYS:
        p = cfg.path("evidence") / f"{t.id}.{play}.json"
        if not p.is_file():
            if play == "build":
                out.append(f"no build evidence {cfg.rel(p)}")
            elif real_stack:
                out.append(f"no test evidence {cfg.rel(p)}: commands.{'/'.join(real_stack)} is configured, so "
                           f"the test play must pass before approval (sdlc run test {t.id})")
            continue
        ev = json.loads(p.read_text(encoding="utf-8"))
        if ev.get("result") != "pass" or ev.get("partial"):
            out.append(f"{play} evidence is not a full passing gate run")
        if play == "build" and t.type == "test" and t.real_stack_proof and not mechanical:
            # A test ticket's build is its real-stack proof. Evidence without that proof (or from
            # before v2.0.0, which did not record it) proves nothing through the real stack,
            # unless a passing test play gave it, as it did for a test ticket before v2.0.0.
            configured = [k for k in real_stack_suites(cfg) if cfg.commands.get(k)]
            test_ev = cfg.path("evidence") / f"{t.id}.test.json"
            tested = test_ev.is_file() and json.loads(test_ev.read_text(encoding="utf-8")).get("result") == "pass"
            if configured and ev.get("real_stack_proof") is not True and not tested:
                out.append(f"build evidence for test ticket {t.id} records no passing real-stack test with one of "
                           f"its AC tags ({', '.join(configured)}); re-run the build")
        if ev.get("dirty"):
            out.append(f"{play} evidence came from a dirty tree; it does not describe any commit")
        if ev.get("commit"):
            proven[play] = str(ev["commit"])
    latest = proven.get("build")
    if "test" in proven:
        if latest and not gitutil.is_ancestor(cfg.root, latest, proven["test"]):
            out.append("test evidence is older than the build evidence; re-run the test play on the new build")
        else:
            latest = proven["test"]
    if latest and not _same_commit(commit, latest):
        out.append(f"review is for {commit[:12] or '(none)'}, but the latest evidence is for {latest[:12]}; "
                   "review the commit that was proven last")
    return out


def _changed_after_review(cfg: Config, t: Ticket, commit: str, base: str | None = None) -> list[str]:
    """An approval covers the reviewed commit. Afterwards only the review itself, the
    ticket's evidence and its status may change; anything else was never reviewed.
    Only what would merge counts: committed files this branch changes against its base.
    Untracked files (an `npm install` lockfile in CI) and files that came in from the base
    branch after the review are not part of the change."""
    try:
        changed = gitutil.committed_between(cfg.root, commit)
    except gitutil.GitError:
        return [f"reviewed commit {commit[:12]} is not in this repository's history"]
    try:
        b = base or cfg.section("vcs").get("base", "main")
        ours = set(gitutil.committed_between(cfg.root, gitutil.merge_base(cfg.root, b)))
        changed = [f for f in changed
                   if f in ours and not gitutil.same_branch_change(cfg.root, b, commit, f, "HEAD")]
    except gitutil.GitError:
        pass  # no base to compare with: every committed change after the review counts
    ev = cfg.data["paths"]["evidence"]
    ok = {f"{cfg.data['paths']['reviews']}/{t.id}.md", *(f"{ev}/{t.id}.{p}.json" for p in EVIDENCE_PLAYS)}
    # A prune after the review, such as one merged in from the base branch, makes the gates
    # stricter and cannot void the approval; an added entry hides a failure it never saw.
    bl = baseline.path(cfg.root, cfg.data["paths"])
    reviewed = baseline.load_at(cfg.root, commit, cfg.rel(bl))
    if reviewed is not None and bl.is_file() and not baseline.grown(reviewed, baseline.load(cfg.root, cfg.rel(bl))):
        ok.add(cfg.rel(bl))
    rel = cfg.rel(t.path)
    late = [f for f in changed if f not in ok and not (f == rel and _status_change(cfg, commit, f))]
    return [f"changed after the reviewed commit {commit[:12]}: {f}" for f in late]


def _as_list(v) -> list[str]:
    return [str(x) for x in (v if isinstance(v, list) else [v] if v not in (None, "") else [])]


def _review_entries(body: str, heading: str) -> list[str]:
    """What a review names under `heading`: the first backticked text of each bullet, or its
    first word. A bare `**` or `*` names nothing: each file is accepted on its own."""
    m = re.search(rf"^{re.escape(heading)}[ \t]*$(.*?)(?=^## |\Z)", body.replace("\r\n", "\n"), re.M | re.S)
    out = []
    for ln in (m.group(1) if m else "").split("\n"):
        b = re.match(r"^\s*[-*]\s+(.*)$", ln)
        if not b:
            continue
        ticks = re.findall(r"`([^`]+)`", b.group(1))
        # An entry must start with a literal path segment: `**/?*` or `*.py` would accept
        # every flagged file at once, and the point is that each one is accepted on its own.
        out += [e for e in (ticks or b.group(1).split()[:1])
                if e.split("/")[0] and not any(ch in e.split("/")[0] for ch in "*?[")]
    return out


def _contract_keys(c) -> dict[str, str]:
    """Every declared contract key with everything it declares: a route's attributes and the
    prose under its heading (payloads, status codes, errors), a page's attributes and prose,
    and the rest of each table and event line (fields)."""
    from .artifacts import ROUTE_LINE_RE, normalize_route_key

    prose: dict[str, str] = {}
    for h, text in c.sections.items():
        key = normalize_route_key(h) if ROUTE_LINE_RE.match(h) else f"page {h.split()[0]}"
        prose[key] = prose.get(key, "") + text
    out = {}
    for r in c.routes:
        attrs = {k: v for k, v in r.attrs.items() if k != "origin"}
        out[r.key] = " ".join(f"{k}={v}" for k, v in sorted(attrs.items())) + "\n" + prose.get(r.key, "").strip()
    for pg in c.pages:
        out[f"page {pg}"] = (" ".join(f"{k}={v}" for k, v in sorted(c.page_attrs.get(pg, {}).items()))
                             + "\n" + prose.get(f"page {pg}", "").strip())
    for x in c.tables:
        out[f"table {x}"] = c.definitions.get(f"table {x}", "")
    for x in c.events:
        out[f"event {x}"] = c.definitions.get(f"event {x}", "")
    return out


def _contract_prose(c) -> list[str]:
    """CONTRACTS text no declared key owns: lines outside every key section, plus sections
    under a heading that names no declared route or page (`### /api conventions`)."""
    from .artifacts import ROUTE_LINE_RE, normalize_route_key

    declared = {r.key for r in c.routes} | {f"page {p}" for p in c.pages}
    out = list(c.rest)
    for h, text in sorted(c.sections.items()):
        key = normalize_route_key(h) if ROUTE_LINE_RE.match(h) else f"page {h.split()[0]}"
        if key not in declared:
            out += [f"### {h}"] + text.split("\n")
    return out


def _dropped(old: str, new: str) -> list[str]:
    """Words a contract key's declaration lost: a narrowed key (a field or status removed)."""
    def word(w: str) -> str:
        return w.split("=", 1)[0] + "=" if "=" in w else w  # an attribute whose value changed is kept

    now = {word(w) for w in new.split()}
    return [w for w in dict.fromkeys(old.split()) if word(w) not in now]


def _contract_ref(key: str) -> str:
    """How a ticket cites a contract key in contracts: (`GET /x`, `/page`, `table_name`)."""
    kind, _, rest = key.partition(" ")
    return rest if kind in ("page", "table", "event") else key


def _declared_lane(d: dict) -> str:
    """Ticket.lane for raw frontmatter."""
    from .artifacts import Ticket

    return Ticket("", Path(), d, "").lane


def _risk_rank(d: dict) -> int:
    from .artifacts import RISKS

    r = str(d.get("risk", "low"))
    return RISKS.index(r) if r in RISKS else 0


def _same_commit(ref: str, full: str) -> bool:
    """`ref` names `full`: an abbreviated sha of at least 7 hex digits, or the full sha."""
    ref = ref.strip().lower()
    return len(ref) >= 7 and re.fullmatch(r"[0-9a-f]+", ref) is not None and full.lower().startswith(ref)


def _glob(path: str, pattern: str) -> bool:
    return paths.match(path, pattern)


def _is_test_beside(f: str, files: list[str], test_globs: list[str]) -> bool:
    if not any(_glob(f, g) for g in test_globs):
        return False
    pf = PurePosixPath(f)
    stem = re.sub(r"(\.(test|spec))?\.[^.]+$", "", pf.name)
    stem = re.sub(r"^test_|_test$", "", stem)
    for src in files:
        ps = PurePosixPath(src)
        if ps.parent == pf.parent or pf.parent.name in ("__tests__", "tests") and pf.parent.parent == ps.parent:
            sstem = re.sub(r"\.[^.]+$", "", ps.name)
            if stem == sstem:
                return True
    return False


def _status_change(cfg: Config, ref: str, rel: str) -> tuple[str, str] | None:
    """(old status, new status) when nothing but status/blocked_by changed in a ticket since `ref`."""
    try:
        ref = gitutil.merge_base(cfg.root, ref)
    except gitutil.GitError:
        pass  # a commit sha, not a branch
    old = gitutil.show(cfg.root, ref, "./" + rel)
    p = cfg.root / rel
    if old is None or not p.is_file():
        return None
    try:
        ofm, obody, _ = fm.split(old)
        nfm, nbody, _ = fm.split(p.read_text(encoding="utf-8"))
        od, nd = fm.parse(ofm or ""), fm.parse(nfm or "")
    except fm.ParseError:
        return None
    statuses = (str(od.get("status", "")), str(nd.get("status", "")))
    for d in (od, nd):
        d.pop("status", None)
        d.pop("blocked_by", None)
    return statuses if od == nd and obody.strip() == nbody.strip() else None


def _norm(b: bytes | None) -> bytes | None:
    return None if b is None else b.replace(b"\r\n", b"\n")


def _read_or_none(p: Path) -> bytes | None:
    return _norm(p.read_bytes()) if p.is_file() else None


def recover(root: Path) -> list[str]:
    """Undo an ac-red run that was killed mid-way: it left the ticket's production files
    reverted to the base branch, and their only copy (uncommitted work included) in the
    backup. Every gate and `sdlc run` calls this first. Returns the restored files."""
    return _restore_red_backup(root, root / RUN_DIR / RED_BACKUP)


def _restore_red_backup(root: Path, backup: Path) -> list[str]:
    """Put back the files ac-red reverted."""
    manifest = backup / "manifest.json"
    restored = []
    if manifest.is_file():
        for f, slot in json.loads(manifest.read_text(encoding="utf-8")).items():
            restored.append(f)
            p = root / f
            if slot is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((backup / slot).read_bytes())
    if backup.exists():
        import shutil

        shutil.rmtree(backup)
    return restored


def _tail(p: Path, n: int) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _sample_path(p: str) -> str:
    return re.sub(r"\{[^}]*\}", "sdlc-smoke-0", p)


def _options(url: str) -> tuple[int | None, set[str]]:
    req = urllib.request.Request(url, method="OPTIONS")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            st, allow = r.status, r.headers.get("Allow", "")
    except urllib.error.HTTPError as e:
        st, allow = e.code, e.headers.get("Allow", "")
    except Exception:
        return None, set()
    return st, {m.strip().upper() for m in allow.split(",") if m.strip()}


def _http(url: str, method: str) -> tuple[int | None, str, str]:
    data = b"{}" if method in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(url, method=method, data=data,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(2000).decode("utf-8", "replace")
    except Exception as e:  # connection refused, timeout
        return None, "", str(e)


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _new_group() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
