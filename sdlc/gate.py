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

from . import extract, fm, gitutil, lint, paths
from .artifacts import Repo, Ticket
from .config import Config

COMMAND_CHECKS = ("lint", "typecheck", "unit", "integration", "e2e", "build", "duplication")
JUNIT_CHECKS = ("unit", "integration", "e2e")
RUN_DIR = ".sdlc-run"
BUILTIN_TEST_FORBID = [
    {"regex": r"\b(it|test|describe)\.only\s*\(", "message": "focused test (.only) hides the rest of the suite"},
    {"regex": r"\b(it|test|describe)\.skip\s*\(|\bxit\s*\(|\bxdescribe\s*\(", "message": "skipped test"},
    {"regex": r"@pytest\.mark\.skip\b|@unittest\.skip\b", "message": "skipped test"},
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
        self.cfg = cfg
        self.repo = Repo(cfg)
        self.play = play
        self.ticket: Ticket | None = self.repo.ticket(ticket_id) if ticket_id else None
        self.base = base or cfg.section("vcs").get("base", "main")
        self.only = only
        self.verbose = verbose
        self.run_dir = cfg.root / RUN_DIR
        (self.run_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.testcases: list[TestCase] = []
        self.junit_used: dict[str, bool] = {}
        self.checks: list[Check] = []
        self._changed: list[str] | None = None
        # test and review answer for what they changed after the build was proven,
        # not for the build's own diff against the base branch.
        if since is None and self.ticket and play in ("test", "review"):
            since = proven_commit(cfg, self.ticket.id, ("build",) if play == "test" else ("test", "build"))
        self.since = since

    # -- plumbing ---------------------------------------------------------
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
        }
        self.write_evidence(ev)
        return ev

    def write_evidence(self, ev: dict) -> Path:
        name = f"{self.ticket.id}.{self.play}.json" if self.ticket else f"{self.play}.json"
        dest = self.run_dir / name
        if self.ticket and self.play in ("build", "test"):
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

    def allowed(self) -> tuple[list[str], set[str]]:
        """(glob patterns, exact paths) the current play may change."""
        cfg, t = self.cfg, self.ticket
        paths = cfg.section("paths")
        globs = list(cfg.section("scope").get("always_allowed", []))
        exact: set[str] = {f"{paths['evidence']}/{t.id}.{p}.json" for p in ("build", "test")} if t else set()
        tests = cfg.section("tests")
        if self.play == "build" and t:
            exact |= set(t.files)
            globs += t.shared
        elif self.play == "test" and t:
            globs += tests.get("integration_globs", [])
        elif self.play == "review" and t:
            exact.add(f"{paths['reviews']}/{t.id}.md")
        return globs, exact

    def check_scope(self, c: Check) -> None:
        if not self.ticket:
            c.status, c.summary = "skip", "no ticket"
            return
        t = self.ticket
        globs, exact = self.allowed()
        tests = self.cfg.section("tests")
        bad = []
        for f in self.changed():
            if f in exact or any(_glob(f, g) for g in globs):
                continue
            if self.play == "build" and tests.get("unit_beside", True) and _is_test_beside(f, t.files, tests.get("globs", [])):
                continue
            if f == self.cfg.rel(t.path) and _only_status_changed(self.cfg, self.since or self.base, f):
                continue
            bad.append(f)
        c.details = [f"outside {self.play} write set: {f}" for f in bad]
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)} file(s) outside the ticket's write set. Revert them, or stop and "
                         f"ask the lead to add them to files:/shared: on {t.id}")
        else:
            c.summary = f"{len(self.changed())} changed file(s), all in scope"

    def check_contracts(self, c: Check) -> None:
        contracts = self.repo.contracts
        declared = {r.key for r in contracts.routes}
        code, errs = extract.code_routes(self.cfg)
        details = list(errs)
        if errs and not code:
            c.status, c.summary, c.details = "fail", "cannot extract routes from code", details
            return
        undeclared = sorted(set(code) - declared)
        for k in undeclared:
            details.append(f"route in code but not in CONTRACTS: {k} ({code[k]})")
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
        port = str(self.cfg.section("app")["port"])
        rendered = cmd.replace("{junit}", str(junit)).replace("{port}", port)
        # Evidence is committed: show a root-relative path so it is the same on every machine.
        shown = cmd.replace("{junit}", self.cfg.rel(junit)).replace("{port}", port)
        code, log = self._shell(c.name, rendered)
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

    def _read_junit(self, source: str, path: Path) -> int:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
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
            self.testcases.append(TestCase(name, st, source))
        return n

    def ac_matrix(self) -> dict:
        if not self.ticket:
            return {}
        out = {}
        for tag in self.ticket.ac_tags():
            pat = re.compile(re.escape(tag) + r"(?!\d)")
            hits = [tc for tc in self.testcases if pat.search(tc.name)]
            st = ("missing" if not hits else "failed" if any(h.status == "failed" for h in hits)
                  else "passed" if any(h.status == "passed" for h in hits) else "skipped")
            out[tag] = {"status": st, "tests": [f"[{h.source}] {h.name}" for h in hits][:10]}
        return out

    def check_ac_coverage(self, c: Check) -> None:
        if not self.ticket:
            c.status, c.summary = "skip", "no ticket"
            return
        if not any(self.junit_used.values()):
            c.status = "fail"
            c.summary = "no test command wrote JUnit ({junit}); AC coverage cannot be proven"
            return
        matrix = self.ac_matrix()
        bad = {k: v for k, v in matrix.items() if v["status"] != "passed"}
        c.details = [f"{k}: {v['status']}" for k, v in matrix.items()]
        if bad:
            c.status = "fail"
            c.summary = (f"{len(bad)}/{len(matrix)} AC without a passing test. Name tests with the tag, e.g. "
                         f"it('{next(iter(bad))} ...')")
        else:
            c.summary = f"all {len(matrix)} AC proven by passing tests"

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
        problems = []
        for f in sorted(changed):
            if paths.match(f, f"{adr_dir}/ADR-*.md") and gitutil.show(cfg.root, mb, "./" + f) is not None:
                problems.append(f"{f}: accepted ADR edited; write a new ADR that supersedes it")
        for t in self.repo.tickets.values():
            rel = cfg.rel(t.path)
            if rel not in changed:
                continue
            old = gitutil.show(cfg.root, mb, "./" + rel)
            if old is None:
                continue
            try:
                ofm, _, _ = fm.split(old)
                old_acs = dict(_acs(fm.parse(ofm or "")))
            except fm.ParseError:
                continue
            new_acs = dict(t.acs)
            spec = str(t.data.get("source_spec", ""))
            for ac, text in old_acs.items():
                if not ac:
                    continue
                if new_acs.get(ac) != text and spec not in changed:
                    what = "removed" if ac not in new_acs else "reworded"
                    problems.append(f"{rel}: {ac} {what} without changing {spec or 'its source_spec'}")
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
            c.status, c.summary = "fail", f"missing {self.cfg.rel(p)}"
            return
        issues = lint.lint_review_file(self.repo, p)
        c.details = [str(i) for i in issues]
        data, _ = fm.load(p)
        ev_problems = _evidence_problems(self.cfg, self.ticket, str(data.get("commit", "")))
        c.details += ev_problems
        if data.get("verdict") == "approve" and ev_problems:
            c.status, c.summary = "fail", "approve without passing build evidence for the reviewed commit"
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
                r = subprocess.run(cmd, shell=True, cwd=self.cfg.root, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=timeout, env=dict(os.environ, CI=os.environ.get("CI", "1")))
                code = r.returncode
            except subprocess.TimeoutExpired:
                lf.write(f"\n[sdlc] timed out after {timeout}s\n")
                code = 124
        return code, log


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
            if ev.get("result") == "pass" and ev.get("commit"):
                return ev["commit"]
    return None


def extract_key(ref: str) -> str:
    from .artifacts import normalize_route_key

    return normalize_route_key(ref.split("#", 1)[-1])


def _evidence_problems(cfg: Config, t: Ticket, commit: str) -> list[str]:
    p = cfg.path("evidence") / f"{t.id}.build.json"
    if not p.is_file():
        return [f"no build evidence {cfg.rel(p)}"]
    ev = json.loads(p.read_text(encoding="utf-8"))
    out = []
    if ev.get("result") != "pass":
        out.append("build evidence result is not pass")
    if ev.get("dirty"):
        out.append("build evidence came from a dirty tree; it does not describe any commit")
    if commit and ev.get("commit") and not (ev["commit"].startswith(commit) or commit.startswith(ev["commit"][:7])):
        out.append(f"build evidence is for {ev['commit'][:10]}, review is for {commit[:10]}")
    return out


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


def _only_status_changed(cfg: Config, ref: str, rel: str) -> bool:
    try:
        ref = gitutil.merge_base(cfg.root, ref)
    except gitutil.GitError:
        pass  # a commit sha, not a branch
    old = gitutil.show(cfg.root, ref, "./" + rel)
    if old is None:
        return False
    new = (cfg.root / rel).read_text(encoding="utf-8")
    try:
        ofm, obody, _ = fm.split(old)
        nfm, nbody, _ = fm.split(new)
        od, nd = fm.parse(ofm or ""), fm.parse(nfm or "")
    except fm.ParseError:
        return False
    for d in (od, nd):
        d.pop("status", None)
        d.pop("blocked_by", None)
    return od == nd and obody.strip() == nbody.strip()


def _tail(p: Path, n: int) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _sample_path(p: str) -> str:
    return re.sub(r"\{[^}]*\}", "sdlc-smoke-0", p)


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
