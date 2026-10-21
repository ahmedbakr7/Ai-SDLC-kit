"""`sdlc run <play> <ticket> --agent <name>`: the conveyor.

    clean tree -> branch -> status in_progress -> [prompt -> agent -> commit -> gate]*N
      -> pass: evidence + status in_review (+ PR)   fail: status blocked with the reason

The agent only ever edits files. Branching, status, commits, gating and retries
are done here, the same way for every agent.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from . import approval, gitutil, paths, prompt, tickets
from .artifacts import Repo
from .config import Config
from .gate import Gate, always_allowed, dirty_tree, recover

INSTRUCTION = ("You are running one play of the ai-sdlc kit. Read the file {prompt_file} completely "
               "and do exactly what it says. It is your entire task. When you are done, stop.")


def agents(cfg: Config) -> dict:
    """Agents are defined by the product in sdlc.toml [agents.<name>]; the kit ships none,
    because how much autonomy an agent gets is the product owner's decision."""
    return cfg.section("agents")


def agent_command(cfg: Config, name: str, prompt_file: Path) -> tuple[str, str | None]:
    reg = agents(cfg)
    if name not in reg:
        raise SystemExit(f"unknown agent {name!r}; define [agents.{name}] in sdlc.toml "
                         f"(configured: {', '.join(sorted(reg)) or 'none'}). See adapters/AGENTS-RUNNER.md")
    a = reg[name]
    rel = cfg.rel(prompt_file)
    instr = INSTRUCTION.format(prompt_file=rel)
    q = (lambda s: subprocess.list2cmdline([s])) if os.name == "nt" else shlex.quote
    cmd = a["command"].replace("{instruction}", q(instr)).replace("{prompt_file}", q(rel))
    stdin = None
    if a.get("stdin") == "prompt":
        stdin = prompt_file.read_text(encoding="utf-8")
    elif a.get("stdin") == "instruction":
        stdin = instr
    return cmd, stdin


def _say(msg: str) -> None:
    print(f"[sdlc run] {msg}", flush=True)


def run(cfg: Config, play: str, tid: str, agent: str, attempts: int | None, base: str | None,
        extra: str = "", dry_run: bool = False, take_over: bool = False) -> int:
    if play not in ("build", "test", "review"):
        raise SystemExit("sdlc run drives build, test and review; lead plays are interactive (use sdlc prompt)")
    root = cfg.root
    vcs = cfg.section("vcs")
    base = base or vcs.get("base", "main")
    attempts = attempts or int(cfg.section("gate").get("max_attempts", 3))
    branch = vcs.get("branch", "{play}/{id}").format(play="build", id=tid)

    restored = recover(root)
    if restored:
        _say(f"restored {len(restored)} file(s) an interrupted ac-red check had reverted: {', '.join(restored)}")
    if dirty_tree(cfg):
        raise SystemExit("working tree is dirty; commit or stash first so every change is attributable")
    if play != "build" and not dry_run:
        # test and review continue the ticket's branch: read its status and history there,
        # not on whatever branch happens to be checked out.
        _checkout(root, branch, base, create=False)
    records = approval.records_mode(cfg)
    push_claim = records and play == "build" and cfg.claim_mode() == "push"
    if take_over and not push_claim:
        raise SystemExit("--take-over continues another run's claim; it needs records mode, build and "
                         "vcs.claim = \"push\"")
    if push_claim and not dry_run:
        _fetch(root)  # claims are judged on what the remote holds now, not on the last fetch
    repo = Repo(cfg)
    t = repo.ticket(tid)

    if records:
        # Status is derived (ADR-0001 step 2): nothing to move, no status or evidence commits.
        if repo.status_of(t) == "done":
            raise SystemExit(f"{tid} is done (a merged commit names it)")
        if play == "build":
            pending = repo.pending_deps(t)
            if t.status != "ready" or pending:
                raise SystemExit(f"refused: {tid} must be ready with its dependencies done"
                                 + (f" (pending: {', '.join(pending)})" if pending else f" (it is {t.status})"))
            if not repo.bases():
                raise SystemExit(f"refused: vcs.base {vcs.get('base', 'main')!r} is neither a local branch nor "
                                 f"on origin, so no branch can be checked for {tid}; fetch it first")
            # Resuming this ticket's own branch is fine; another branch already building it is not.
            elsewhere = [b for b in repo.in_flight().get(tid, []) if b not in (branch, f"origin/{branch}")]
            if elsewhere:
                raise SystemExit(f"refused: {tid} is in progress on {', '.join(elsewhere)}; finish or delete "
                                 "that branch first")
            if push_claim:
                _claim_problem(root, repo, tid, branch, take_over)
        elif play == "test" and not t.test_play:
            raise SystemExit(f"{tid} has no test play ({t.no_test_play_reason}); review it after the build")
    elif play == "build":
        if t.status == "ready":
            try:
                tickets.check_transition(repo, t, "in_progress", "build")
            except tickets.TransitionError as e:
                raise SystemExit(f"refused: {e}") from None
        elif t.status != "in_progress":
            raise SystemExit(f"{tid} is {t.status}; build starts from ready or in_progress")
    elif t.status != "in_review":
        raise SystemExit(f"{play} runs on tickets in_review; {tid} is {t.status}")
    elif play == "test" and not t.test_play:
        raise SystemExit(f"{tid} has no test play ({t.no_test_play_reason}); review it after the build")

    if play == "review" and cfg.section("review").get("require_distinct_agent", True):
        authors = _authors(root, base)
        if agent in authors:
            raise SystemExit(f"{tid} has build/test commits by {agent}; review it with a different agent "
                             f"(authors: {', '.join(sorted(authors))})")

    if dry_run:
        p = prompt.write(cfg, play, tid, prompt.render(cfg, play, tid, extra=extra))
        cmd, _ = agent_command(cfg, agent, p)
        _say(f"would checkout {branch}, run: {cmd}")
        return 0

    if play == "build":
        prev = gitutil.git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if prev == "HEAD":
            prev = gitutil.head(root)
        created = not _exists(root, branch)
        _checkout(root, branch, base, create=True)
        if push_claim:
            _push_claim(cfg, tid, branch, base, agent, prev, created)
    leave = _leave(cfg, play, tid, base)
    # test and review are judged on what changed after this point. Taken before any agent
    # runs, so no file the agent can write (e.g. evidence) can move it.
    since = gitutil.head(root) if play != "build" else None
    if play == "build" and t.status == "ready" and not records:
        tickets.set_status(repo, t, "in_progress", "build")
        _commit(root, f"start {tid}: {t.data.get('title')}", agent, play, tid)

    feedback = ""
    for n in range(1, attempts + 1):
        _say(f"{play} {tid} attempt {n}/{attempts} with {agent}")
        text = prompt.render(cfg, play, tid, feedback=feedback, extra=extra)
        pf = prompt.write(cfg, play, tid, text)
        cmd, stdin = agent_command(cfg, agent, pf)
        before = gitutil.head(root)
        log = cfg.root / ".sdlc-run" / "logs" / f"agent-{play}-{tid}-{n}.log"
        code, secs = _run_agent(cmd, stdin, root, int(agents(cfg)[agent].get("timeout", 3600)), log)
        _say(f"agent exited {code} after {secs}s; output: {cfg.rel(log)}")
        problem = _history_problem(root, branch, before)
        if problem:
            # Never commit onto a branch the agent switched to, or over history it rewrote.
            _say(f"stopped: {problem}")
            return 1
        _commit(root, f"{play} {tid}: {t.data.get('title')} (attempt {n})", agent, play, tid, leave)
        g = Gate(cfg, play, tid, base, since=since)
        ev = g.run(on_check=_report)
        if ev["result"] == "pass":
            repo = Repo(cfg)
            if play == "build" and not records:
                tickets.set_status(repo, repo.ticket(tid), "in_review", "build")
            _commit(root, f"evidence {tid}: {play} gate pass", agent, play, tid, leave)
            if records and play == "review":
                _say(f"review record at .sdlc-run/review-{tid}.md; publish it: sdlc review publish {tid} --pr <n>")
            _say(f"gate passed; evidence at {ev['path']}")
            _open_pr(cfg, branch, base, tid, play)
            return 0
        feedback = _feedback(ev)
        _commit(root, f"evidence {tid}: {play} gate fail (attempt {n})", agent, play, tid, leave)

    repo = Repo(cfg)
    failed = [c["name"] for c in ev["checks"] if c["status"] == "fail"]
    if play == "build" and not records:
        tickets.set_status(repo, repo.ticket(tid), "blocked", "build",
                           reason=f"gate failed after {attempts} attempts: {', '.join(failed)}")
        _commit(root, f"block {tid}: gate failed", agent, play, tid)
    _say(f"gate still failing after {attempts} attempts: {', '.join(failed)}")
    return 1


def _run_agent(cmd: str, stdin: str | None, root: Path, timeout: int, log: Path) -> tuple[int, int]:
    """Run the agent with its output in a log; on timeout kill its whole process tree."""
    from .gate import _kill, _new_group

    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(log, "w", encoding="utf-8") as lf:
        lf.write(f"$ {cmd}\n")
        lf.flush()
        proc = subprocess.Popen(cmd, shell=True, cwd=root, stdout=lf, stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                text=True, encoding="utf-8", **_new_group())
        try:
            proc.communicate(stdin, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            _kill(proc)
            lf.write(f"\n[sdlc run] agent killed after {timeout}s\n")
            code = 124
    return code, int(time.monotonic() - t0)


def _history_problem(root: Path, branch: str, before: str) -> str:
    cur = gitutil.git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if cur != branch:
        return f"the agent left {branch} (now on {cur}); nothing was committed"
    if not gitutil.is_ancestor(root, before, "HEAD"):
        return f"the agent rewrote history on {branch} ({before[:10]} is no longer an ancestor of HEAD)"
    return ""


def _report(c) -> None:
    _say(f"  {c.status:4} {c.name}: {c.summary}")
    if c.status == "fail":
        for d in c.details[:8]:
            _say(f"         {d}")


def _feedback(ev: dict) -> str:
    out = []
    for c in ev["checks"]:
        if c["status"] != "fail":
            continue
        out.append(f"### {c['name']}: {c['summary']}")
        if c["details"]:
            out.append("```\n" + "\n".join(c["details"][-60:]) + "\n```")
        if c.get("log"):
            out.append(f"Full log: `{c['log']}`")
    return "\n".join(out)


def _exists(root: Path, ref: str) -> bool:
    return bool(gitutil.git(root, "rev-parse", "--verify", "--quiet", ref, check=False).strip())


def _fetch(root: Path) -> None:
    """vcs.claim = "push": every branch on origin, pruned, so a deleted claim frees its ticket."""
    try:
        gitutil.git(root, "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    except gitutil.GitError as e:
        raise SystemExit(f"refused: vcs.claim = \"push\" fetches origin before claiming, and the fetch "
                         f"failed: {e}") from None


def _claim_problem(root: Path, repo: Repo, tid: str, branch: str, take_over: bool) -> None:
    """vcs.claim = "push" (ADR-0005): the ticket's branch on origin is another run's claim unless
    this clone has the branch too, or the claim expired. Same name, so `origin/<branch>` alone
    cannot tell this run's own claim from someone else's: continuing it takes --take-over."""
    remote = f"origin/{branch}"
    held = remote in repo.in_flight().get(tid, [])
    if held and not _exists(root, branch) and not take_over:
        who = gitutil.git(root, "log", "-1", "--format=%an, %cr", f"refs/remotes/{remote}").strip()
        raise SystemExit(f"refused: {tid} is claimed by {remote} (last commit: {who}); if that run is yours "
                         "or abandoned, continue it with --take-over")
    if _exists(root, branch) and _exists(root, f"refs/remotes/{remote}") \
            and not gitutil.is_ancestor(root, f"refs/remotes/{remote}", branch):
        raise SystemExit(f"refused: {branch} and {remote} have diverged; another run may have claimed "
                         f"{tid}. Reconcile the two (or delete your {branch}) first")


def _push_claim(cfg: Config, tid: str, branch: str, base: str, agent: str, prev: str, created: bool) -> None:
    """Push the ticket's branch with a fresh empty claim commit before any agent runs, every
    time: a resumed, expired or taken-over branch already names the ticket, and pushing it
    unchanged would succeed for every run at once. Each claim is a distinct commit (a nonce
    trailer, so one identity on one tick cannot make two equal ones), so of two runs git refuses
    the second push (no force), and the holder a take-over displaced is refused on its next push.
    A failure puts the branch back as it was."""
    import uuid

    root = cfg.root
    before = gitutil.head(root)

    def undo() -> None:
        if created:
            gitutil.git(root, "checkout", "-q", prev)
            gitutil.git(root, "branch", "-q", "-D", branch)
        else:
            gitutil.git(root, "reset", "-q", "--hard", before)  # the tree was clean; the claim is empty
            gitutil.git(root, "checkout", "-q", prev)

    try:
        gitutil.git(root, "commit", "-q", "--allow-empty", "-m", f"claim {tid}", "--trailer", f"Sdlc-Agent: {agent}",
                    "--trailer", "Sdlc-Play: build", "--trailer", f"Sdlc-Ticket: {tid}",
                    "--trailer", f"Sdlc-Claim: {uuid.uuid4()}")
    except gitutil.GitError as e:
        undo()
        raise SystemExit(f"refused: could not commit the claim for {tid}: {e}") from None
    r = subprocess.run(["git", "push", "-q", "origin", f"{branch}:refs/heads/{branch}"], cwd=root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        undo()
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise SystemExit(f"refused: could not claim {tid} by pushing {branch} (another run may have claimed it "
                         f"first; fetch and check `sdlc status`): {msg[-1] if msg else r.returncode}")
    _say(f"claimed {tid}: pushed {branch} to origin")


def _checkout(root: Path, branch: str, base: str, create: bool) -> None:
    exists = lambda ref: _exists(root, ref)

    if exists(branch):
        gitutil.git(root, "checkout", "-q", branch)
    elif exists(f"refs/remotes/origin/{branch}"):
        # Resume the ticket's fetched branch with its commits, not a fresh one from the base.
        gitutil.git(root, "checkout", "-q", "-b", branch, f"origin/{branch}")
    elif create:
        gitutil.git(root, "checkout", "-q", "-b", branch, gitutil.merge_base(root, base))
    else:
        raise SystemExit(f"branch {branch} does not exist; run build first")


def _leave(cfg: Config, play: str, tid: str, base: str) -> Callable[[str], bool] | None:
    """What the runner leaves uncommitted. The test and review write sets are hard, so an
    untracked always_allowed file a tool wrote there (`npm install` and a lockfile the product
    does not commit) would fail scope once committed; it stays untracked unless the play's write
    set covers it. A change to a tracked one is committed and judged: it changes what the commit
    ships. A build commits both: a dependency change ships with the PR, and the review names it."""
    if play == "build" or not cfg.section("scope").get("always_allowed"):
        return None
    globs, exact = Gate(cfg, play, tid, base).allowed()
    return lambda f: (always_allowed(cfg, f) and f not in exact
                      and not any(paths.match(f, g) for g in globs))


def _commit(root: Path, msg: str, agent: str, play: str, tid: str,
            leave: Callable[[str], bool] | None = None) -> None:
    kept = gitutil.new_files(root, [f for f in gitutil.untracked(root) if leave(f)]) if leave else []
    gitutil.git(root, "add", "-A")
    if kept:
        gitutil.git(root, "reset", "-q", "--", *(f":(literal){f}" for f in kept))
        _say(f"left untracked (scope.always_allowed, outside the {play} write set): {', '.join(kept)}")
    if not gitutil.git(root, "diff", "--cached", "--name-only").strip():
        return
    # Sdlc-Ticket is what derived status reads once the commit reaches the base branch.
    # --trailer, as `sdlc commit` does: a message's own trailers stay in the same block.
    gitutil.git(root, "commit", "-q", "-m", msg, "--trailer", f"Sdlc-Agent: {agent}",
                "--trailer", f"Sdlc-Play: {play}", "--trailer", f"Sdlc-Ticket: {tid}")


def _authors(root: Path, base: str) -> set[str]:
    """Agents with a non-review commit on this branch (a commit with no Sdlc-Play counts)."""
    return gitutil.build_agents(root, f"{gitutil.merge_base(root, base)}..HEAD")


def _open_pr(cfg: Config, branch: str, base: str, tid: str, play: str) -> None:
    cmd = cfg.section("vcs").get("pr_command", "")
    if not cmd or play != "build":
        _say(f"next: push {branch} and open a PR into {base}" if play == "build" else "done")
        return
    rendered = cmd.format(branch=branch, base=base, id=tid)
    r = subprocess.run(rendered, shell=True, cwd=cfg.root)
    if r.returncode != 0:
        print(f"[sdlc run] pr_command failed ({r.returncode}); push {branch} manually", file=sys.stderr)
