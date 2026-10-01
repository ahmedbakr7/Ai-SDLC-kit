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
    repo = Repo(cfg)
    t = repo.ticket(tid)
    root = cfg.root
    vcs = cfg.section("vcs")
    base = base or vcs.get("base", "main")
    attempts = attempts or int(cfg.section("gate").get("max_attempts", 3))

    if gitutil.is_dirty(root):
        raise SystemExit("working tree is dirty; commit or stash first so every change is attributable")

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
        built_by = _built_by(root, base)
        if built_by == agent:
            raise SystemExit(f"{tid} was built by {agent}; review it with a different agent")

    branch = vcs.get("branch", "{play}/{id}").format(play="build", id=tid)
    if dry_run:
        p = prompt.write(cfg, play, tid, prompt.render(cfg, play, tid, extra=extra))
        cmd, _ = agent_command(cfg, agent, p)
        _say(f"would checkout {branch}, run: {cmd}")
        return 0

    _checkout(root, branch, base, create=(play == "build"))
    if play == "build" and t.status == "ready":
        tickets.set_status(repo, t, "in_progress", "build")
        _commit(root, f"start {tid}: {t.data.get('title')}", agent)

    feedback = ""
    for n in range(1, attempts + 1):
        _say(f"{play} {tid} attempt {n}/{attempts} with {agent}")
        text = prompt.render(cfg, play, tid, feedback=feedback, extra=extra)
        pf = prompt.write(cfg, play, tid, text)
        cmd, stdin = agent_command(cfg, agent, pf)
        t0 = time.monotonic()
        r = subprocess.run(cmd, shell=True, cwd=root, input=stdin, text=True if stdin else None,
                           timeout=int(agents(cfg)[agent].get("timeout", 3600)))
        _say(f"agent exited {r.returncode} after {int(time.monotonic() - t0)}s")
        _commit(root, f"{play} {tid}: {t.data.get('title')} (attempt {n})", agent)
        g = Gate(cfg, play, tid, base)
        ev = g.run(on_check=_report)
        if ev["result"] == "pass":
            repo = Repo(cfg)
            if play == "build":
                tickets.set_status(repo, repo.ticket(tid), "in_review", "build")
            _commit(root, f"evidence {tid}: {play} gate pass", agent)
            _say(f"gate passed; evidence at {ev['path']}")
            _open_pr(cfg, branch, base, tid, play)
            return 0
        feedback = _feedback(ev)
        _commit(root, f"evidence {tid}: {play} gate fail (attempt {n})", agent)

    repo = Repo(cfg)
    failed = [c["name"] for c in ev["checks"] if c["status"] == "fail"]
    if play == "build":
        tickets.set_status(repo, repo.ticket(tid), "blocked", "build",
                           reason=f"gate failed after {attempts} attempts: {', '.join(failed)}")
        _commit(root, f"block {tid}: gate failed", agent)
    _say(f"gate still failing after {attempts} attempts: {', '.join(failed)}")
    return 1


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


def _commit(root: Path, msg: str, agent: str) -> None:
    gitutil.git(root, "add", "-A")
    if not gitutil.git(root, "diff", "--cached", "--name-only").strip():
        return
    gitutil.git(root, "commit", "-q", "-m", msg, "-m", f"Sdlc-Agent: {agent}")


def _built_by(root: Path, base: str) -> str:
    log = gitutil.git(root, "log", f"{gitutil.merge_base(root, base)}..HEAD", "--format=%B", check=False)
    for line in log.splitlines():
        if line.startswith("Sdlc-Agent:"):
            return line.split(":", 1)[1].strip()
    return ""


def _open_pr(cfg: Config, branch: str, base: str, tid: str, play: str) -> None:
    cmd = cfg.section("vcs").get("pr_command", "")
    if not cmd or play != "build":
        _say(f"next: push {branch} and open a PR into {base}" if play == "build" else "done")
        return
    rendered = cmd.format(branch=branch, base=base, id=tid)
    r = subprocess.run(rendered, shell=True, cwd=cfg.root)
    if r.returncode != 0:
        print(f"[sdlc run] pr_command failed ({r.returncode}); push {branch} manually", file=sys.stderr)
