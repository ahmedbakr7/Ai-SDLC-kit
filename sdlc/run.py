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

from . import gitutil, prompt, tickets
from .artifacts import Repo
from .config import Config
from .gate import Gate

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
        extra: str = "", dry_run: bool = False) -> int:
    if play not in ("build", "test", "review"):
        raise SystemExit("sdlc run drives build, test and review; lead plays are interactive (use sdlc prompt)")
    root = cfg.root
    vcs = cfg.section("vcs")
    base = base or vcs.get("base", "main")
    attempts = attempts or int(cfg.section("gate").get("max_attempts", 3))
    branch = vcs.get("branch", "{play}/{id}").format(play="build", id=tid)

    if gitutil.is_dirty(root):
        raise SystemExit("working tree is dirty; commit or stash first so every change is attributable")
    if play != "build" and not dry_run:
        # test and review continue the ticket's branch: read its status and history there,
        # not on whatever branch happens to be checked out.
        _checkout(root, branch, base, create=False)
    repo = Repo(cfg)
    t = repo.ticket(tid)

    if play == "build":
        if t.status == "ready":
            try:
                tickets.check_transition(repo, t, "in_progress", "build")
            except tickets.TransitionError as e:
                raise SystemExit(f"refused: {e}") from None
        elif t.status != "in_progress":
            raise SystemExit(f"{tid} is {t.status}; build starts from ready or in_progress")
    elif t.status != "in_review":
        raise SystemExit(f"{play} runs on tickets in_review; {tid} is {t.status}")

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
        _checkout(root, branch, base, create=True)
    # test and review are judged on what changed after this point. Taken before any agent
    # runs, so no file the agent can write (e.g. evidence) can move it.
    since = gitutil.head(root) if play != "build" else None
    if play == "build" and t.status == "ready":
        tickets.set_status(repo, t, "in_progress", "build")
        _commit(root, f"start {tid}: {t.data.get('title')}", agent, play)

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
        _commit(root, f"{play} {tid}: {t.data.get('title')} (attempt {n})", agent, play)
        g = Gate(cfg, play, tid, base, since=since)
        ev = g.run(on_check=_report)
        if ev["result"] == "pass":
            repo = Repo(cfg)
            if play == "build":
                tickets.set_status(repo, repo.ticket(tid), "in_review", "build")
            _commit(root, f"evidence {tid}: {play} gate pass", agent, play)
            _say(f"gate passed; evidence at {ev['path']}")
            _open_pr(cfg, branch, base, tid, play)
            return 0
        feedback = _feedback(ev)
        _commit(root, f"evidence {tid}: {play} gate fail (attempt {n})", agent, play)

    repo = Repo(cfg)
    failed = [c["name"] for c in ev["checks"] if c["status"] == "fail"]
    if play == "build":
        tickets.set_status(repo, repo.ticket(tid), "blocked", "build",
                           reason=f"gate failed after {attempts} attempts: {', '.join(failed)}")
        _commit(root, f"block {tid}: gate failed", agent, play)
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


def _checkout(root: Path, branch: str, base: str, create: bool) -> None:
    exists = gitutil.git(root, "rev-parse", "--verify", "--quiet", branch, check=False).strip()
    if exists:
        gitutil.git(root, "checkout", "-q", branch)
    elif create:
        gitutil.git(root, "checkout", "-q", "-b", branch, gitutil.merge_base(root, base))
    else:
        raise SystemExit(f"branch {branch} does not exist; run build first")


def _commit(root: Path, msg: str, agent: str, play: str) -> None:
    gitutil.git(root, "add", "-A")
    if not gitutil.git(root, "diff", "--cached", "--name-only").strip():
        return
    gitutil.git(root, "commit", "-q", "-m", msg, "-m", f"Sdlc-Agent: {agent}\nSdlc-Play: {play}")


def _authors(root: Path, base: str) -> set[str]:
    """Agents with a non-review commit on this branch (a commit with no Sdlc-Play counts)."""
    log = gitutil.git(root, "log", f"{gitutil.merge_base(root, base)}..HEAD",
                      "--format=%(trailers:key=Sdlc-Agent,valueonly,separator=%x2C)|"
                      "%(trailers:key=Sdlc-Play,valueonly,separator=%x2C)", check=False)
    out = set()
    for line in log.splitlines():
        agent, _, play = line.partition("|")
        if agent.strip() and play.strip() != "review":
            out.add(agent.strip())
    return out


def _open_pr(cfg: Config, branch: str, base: str, tid: str, play: str) -> None:
    cmd = cfg.section("vcs").get("pr_command", "")
    if not cmd or play != "build":
        _say(f"next: push {branch} and open a PR into {base}" if play == "build" else "done")
        return
    rendered = cmd.format(branch=branch, base=base, id=tid)
    r = subprocess.run(rendered, shell=True, cwd=cfg.root)
    if r.returncode != 0:
        print(f"[sdlc run] pr_command failed ({r.returncode}); push {branch} manually", file=sys.stderr)
