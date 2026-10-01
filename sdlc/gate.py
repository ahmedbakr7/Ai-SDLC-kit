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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from . import config, extract, fm, gitutil, lint, paths, tickets
from .artifacts import AC_TAG_RE, Repo, Ticket, normalize_path
from .config import Config

TICKET_PLAYS = ("build", "test", "review")
EVIDENCE_PLAYS = ("build", "test")  # plays whose passing evidence is committed under evidence/
# `gate pr <id>` judges one ticket's whole branch (build + test + review + the merge's `done`).
PR_ROLES = ("build", "test", "review", "merge")
COMMAND_CHECKS = ("lint", "typecheck", "unit", "integration", "e2e", "build", "duplication")
JUNIT_CHECKS = ("unit", "integration", "e2e")
RUN_DIR = ".sdlc-run"
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


@dataclass
class TestCase:
    name: str
    status: str  # passed | failed | skipped
    source: str


class Gate:
    def __init__(self, cfg: Config, play: str, ticket_id: str | None, base: str | None,
                 only: list[str] | None = None, verbose: bool = False, since: str | None = None):
        self.base = base or cfg.section("vcs").get("base", "main")
        self.config_note = ""
        if ticket_id and play in (*TICKET_PLAYS, "pr"):
            cfg = self._trusted_config(cfg)
        self.cfg = cfg
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
            since = _evidence_commit(cfg, self.ticket.id, ("build",) if play == "test" else EVIDENCE_PLAYS)
        self.since = since

    # -- plumbing ---------------------------------------------------------
    def _trusted_config(self, cfg: Config) -> Config:
        """A ticket play is judged by the base branch's sdlc.toml, never by the branch under
        test: otherwise the agent being gated could drop a check or swap a command."""
        try:
            mb = gitutil.merge_base(cfg.root, self.base)
        except gitutil.GitError:
            return cfg
        committed = gitutil.show(cfg.root, mb, "./" + config.CONFIG_NAME)
        if committed is None:
            return cfg
        trusted = config.load(cfg.root, text=committed)
        if trusted.data != cfg.data:
            self.config_note = (f"{config.CONFIG_NAME} differs from {self.base}; this gate used the "
                                f"{self.base} version. Config changes go to {self.base} first, not in a ticket.")
        return trusted

    def plan(self) -> list[str]:
        g = self.cfg.section("gate")
        if self.play not in g:
            raise SystemExit(f"no gate defined for play {self.play!r}")
        names = list(g[self.play])
        if self.only:
            names = [n for n in names if n in self.only]
        return names

    def changed(self) -> list[str]:
        if self._changed is None:
            if self.since:
                self._changed = gitutil.changed_since(self.cfg.root, self.since)
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
            self.checks.append(c)
            if on_check:
                on_check(c)
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
            "ac": self.ac_matrix() if self.ticket else {},
            "config_note": self.config_note,
        }
        if self.only:
            ev["partial"] = True  # a subset of the play's checks proves nothing about the play
        self.write_evidence(ev)
        return ev

    def write_evidence(self, ev: dict) -> Path:
        name = f"{self.ticket.id}.{self.play}.json" if self.ticket else f"{self.play}.json"
        dest = self.run_dir / name
        if self.ticket and self.play in EVIDENCE_PLAYS and not ev.get("partial"):
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
            if t.status not in ("in_progress", "in_review"):
                c.status = "fail"
                c.details.append(f"{t.id} status is {t.status}; run `sdlc status {t.id} in_progress --as build` first")
            pending = [d for d in t.depends_on if self.repo.tickets.get(d) and self.repo.tickets[d].status != "done"]
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
        exact: set[str] = set()
        if not t:
            return globs, exact
        tests = cfg.section("tests")
        for play in roles or self.roles():
            # A play may write only its own evidence: test/review must not rewrite the build's proof.
            if play in EVIDENCE_PLAYS:
                exact.add(f"{paths['evidence']}/{t.id}.{play}.json")
            if play == "build":
                exact |= set(t.files)
                globs += t.shared
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
            done_at = gitutil.git(self.cfg.root, "log", "-1", "--format=%H", "--", anchor, check=False).strip()
            if not done_at:
                continue
            touched = set(gitutil.changed_since(self.cfg.root, done_at))
            globs, exact = self.allowed((play,))
            out.append(lambda f, g=globs, e=exact, tch=touched: f not in tch and (f in e or any(_glob(f, x) for x in g)))
        return out

    def check_scope(self, c: Check) -> None:
        if not self.ticket:
            c.status, c.summary = "skip", "no ticket"
            return
        t = self.ticket
        globs, exact = self.allowed()
        tests = self.cfg.section("tests")
        earlier = self._earlier_play_outputs() if self.play == "build" else []
        bad, moves = [], []
        for f in self.changed():
            if f in exact or any(_glob(f, g) for g in globs):
                continue
            if any(ok(f) for ok in earlier):
                continue
            if ("build" in self.roles() and tests.get("unit_beside", True)
                    and _is_test_beside(f, t.files, tests.get("globs", []))):
                continue
            if f == self.cfg.rel(t.path) and (move := _status_change(self.cfg, self.since or self.base, f)):
                # Only the status may change, and only along moves this play's role may make
                # (a test agent cannot mark its own ticket done).
                if tickets.reachable(*move, self.roles()):
                    continue
                moves.append(f"{f}: status {move[0]} -> {move[1]} is not a move the {self.play} play may make")
            bad.append(f)
        c.details = moves + [f"outside {self.play} write set: {f}" for f in bad]
        if self.config_note:
            c.details.append(self.config_note)
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)} file(s) outside the ticket's write set. Revert them, or stop and "
                         f"ask the lead to add them to files:/shared: on {t.id}")
        else:
            c.summary = f"{len(self.changed())} changed file(s), all in scope"

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
        stray = [(f, ln, p) for f, ln, p in extract.client_calls(self.cfg) if not extract.path_matches(p, paths)]
        for f, ln, p in stray:
            details.append(f"client calls {p} at {f}:{ln}, which no contract route serves")
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
        shipped = [t for _, t in sorted(self.repo.tickets.items()) if t.status in ("in_review", "done")]
        targets = [self.ticket] if self.ticket else shipped
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
        c.details = [f"{k}: {v['status']}" for k, v in matrix.items() if self.ticket or v["status"] != "passed"]
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)}/{len(matrix)} AC without a passing test. Name tests with the tag, e.g. "
                         f"it('{next(iter(bad))} ...')")
        else:
            c.summary = f"all {len(matrix)} AC of {len(targets)} ticket(s) proven by passing tests"
        if self.play == "test" and self.ticket:
            # The test play exists to prove AC through the real stack; unit proof alone is the build's.
            real = [tc for tc in self.testcases if tc.source != "unit" and tc.status == "passed"
                    and AC_TAG_RE.search(tc.name) and self.ticket.id in tc.name]
            if not real:
                c.status = "fail"
                c.summary = (f"no passing integration/e2e test carries a {self.ticket.id}/AC-n tag; "
                             "the test play must prove AC through the real stack")

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
        test_globs = self.cfg.section("tests").get("globs", [])
        prod = sorted(f for f in set(t.files) | {f for f in self.changed() if any(_glob(f, g) for g in t.shared)}
                      if not any(_glob(f, g) for g in test_globs))
        mb = gitutil.merge_base(self.cfg.root, self.base)
        prod = [f for f in prod if _norm(gitutil.show_bytes(self.cfg.root, mb, "./" + f)) != _read_or_none(self.cfg.root / f)]
        if not prod:
            c.status, c.summary = "skip", f"no production file of {t.id} differs from {self.base}; nothing to revert"
            return
        backup = self.run_dir / "red-backup"
        _restore_red_backup(self.cfg.root, backup)  # a previous run that was killed mid-way
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
                if old is None:
                    p.unlink(missing_ok=True)
                else:
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
        green = []
        for tag in t.ac_tags():
            pat = re.compile(re.escape(tag) + r"(?!\d)")
            hits = [tc for tc in cases if pat.search(tc.name)]
            if hits and all(h.status == "passed" for h in hits):
                green.append(f"{tag}: passes without this ticket's code ({'; '.join(h.name for h in hits[:3])})")
        c.details = green
        if green:
            c.status = "fail"
            c.summary = (f"{len(green)} AC proven only by tests that pass with {', '.join(prod) or 'nothing'} "
                         f"reverted to {self.base}; assert on what this ticket built")
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
                 or (owner in self.repo.tickets and self.repo.tickets[owner].status in live)]
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
                c.status, c.summary = "fail", f"{len(problems)} of {len(routes) + len(pages)} probe(s) failed"
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
        for t in self.repo.tickets.values():
            rel = cfg.rel(t.path)
            if rel not in changed:
                continue
            old = _frontmatter(gitutil.show(cfg.root, mb, "./" + rel))
            if old is None or old.get("status") in ("draft", None):
                continue  # AC are not accepted until the lead makes the ticket ready
            old_acs = dict(_acs(old))
            new_acs = dict(t.acs)
            # An AC may change only together with a requirement it serves: the spec decides.
            cited = [str(r) for r in (old.get("requirements") or [])]
            spec = str(old.get("source_spec", ""))
            reqs_then = _requirements_at(cfg, mb, spec)
            moved = [r for r in cited if reqs_then.get(r) != reqs_now.get(r)]
            for ac, text in old_acs.items():
                if ac and new_acs.get(ac) != text and not moved:
                    what = "removed" if ac not in new_acs else "reworded"
                    problems.append(f"{rel}: {ac} {what}, but none of its requirements "
                                    f"({', '.join(cited) or 'none'}) changed in {spec or 'its source_spec'}")
        c.details = problems
        if problems:
            c.status, c.summary = "fail", f"{len(problems)} immutable artifact(s) changed"
        else:
            c.summary = "no accepted ADR edited, no AC weakened"

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
            c.status, c.summary = "fail", "review needs a ticket"
            return
        p = self.cfg.path("reviews") / f"{self.ticket.id}.md"
        if not p.is_file():
            if self.play == "pr" and self.ticket.status != "done":
                c.status, c.summary = "skip", "not reviewed yet (ticket is not done)"
                return
            c.status, c.summary = "fail", f"missing {self.cfg.rel(p)}"
            return
        issues = lint.lint_review_file(self.repo, p)
        c.details = [str(i) for i in issues]
        data, _ = fm.load(p)
        ev_problems = _evidence_problems(self.cfg, self.ticket, str(data.get("commit", "")))
        if data.get("verdict") == "approve" and not ev_problems:
            ev_problems = _changed_after_review(self.cfg, self.ticket, str(data.get("commit", "")))
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


def proven_commit(cfg: Config, tid: str, plays: tuple[str, ...]) -> str | None:
    """Commit of the first passing evidence found among `plays` (latest play first)."""
    for play in plays:
        p = cfg.path("evidence") / f"{tid}.{play}.json"
        if p.is_file():
            ev = json.loads(p.read_text(encoding="utf-8"))
            if ev.get("result") == "pass" and ev.get("commit") and not ev.get("partial"):
                return ev["commit"]
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
    """Problems with approving `commit`: build (and test, once it ran) must have passed on a
    clean tree, and the review must name the commit the latest of them proved."""
    out: list[str] = []
    proven: dict[str, str] = {}
    for play in EVIDENCE_PLAYS:
        p = cfg.path("evidence") / f"{t.id}.{play}.json"
        if not p.is_file():
            if play == "build":
                out.append(f"no build evidence {cfg.rel(p)}")
            continue
        ev = json.loads(p.read_text(encoding="utf-8"))
        if ev.get("result") != "pass" or ev.get("partial"):
            out.append(f"{play} evidence is not a full passing gate run")
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


def _changed_after_review(cfg: Config, t: Ticket, commit: str) -> list[str]:
    """An approval covers the reviewed commit. Afterwards only the review itself, the
    ticket's evidence and its status may change; anything else was never reviewed."""
    try:
        changed = gitutil.changed_since(cfg.root, commit)
    except gitutil.GitError:
        return [f"reviewed commit {commit[:12]} is not in this repository's history"]
    ev = cfg.data["paths"]["evidence"]
    ok = {f"{cfg.data['paths']['reviews']}/{t.id}.md", *(f"{ev}/{t.id}.{p}.json" for p in EVIDENCE_PLAYS)}
    rel = cfg.rel(t.path)
    late = [f for f in changed if f not in ok and not (f == rel and _status_change(cfg, commit, f))]
    return [f"changed after the reviewed commit {commit[:12]}: {f}" for f in late]


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


def _restore_red_backup(root: Path, backup: Path) -> None:
    """Put back the files ac-red reverted (also recovers from a run killed mid-way)."""
    manifest = backup / "manifest.json"
    if manifest.is_file():
        for f, slot in json.loads(manifest.read_text(encoding="utf-8")).items():
            p = root / f
            if slot is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((backup / slot).read_bytes())
    if backup.exists():
        import shutil

        shutil.rmtree(backup)


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
