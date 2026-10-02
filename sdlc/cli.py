"""sdlc: deterministic conveyor for the ai-sdlc kit. Python >= 3.11, stdlib only."""
from __future__ import annotations

import argparse
import os
import json
import shutil
import sys
from pathlib import Path

from . import __version__, adapters, config, fm, lint, prompt, skills, tickets, trace
from .artifacts import Repo

EXIT_FAIL = 1


def _cfg(args) -> config.Config:
    cfg = config.load(Path(args.root) if getattr(args, "root", None) else None)
    for w in cfg.warnings:
        print(f"warn: {w}", file=sys.stderr)
    return cfg


def cmd_lint(args) -> int:
    cfg = _cfg(args)
    issues = lint.lint_repo(Repo(cfg), args.ticket)
    for i in issues:
        print(i)
    errs = sum(1 for i in issues if i.level == "error")
    print(f"{errs} error(s), {len(issues) - errs} warning(s)")
    return EXIT_FAIL if errs or (args.strict and issues) else 0


def cmd_trace(args) -> int:
    cfg = _cfg(args)
    m = trace.matrix(Repo(cfg))
    probs = trace.problems(m)
    if args.json:
        print(json.dumps({"matrix": m, "problems": probs}, indent=2))
    else:
        print(trace.render(m))
        for p in probs:
            print(f"ERROR {p}")
    return EXIT_FAIL if probs else 0


def cmd_next(args) -> int:
    cfg = _cfg(args)
    q = tickets.ready_queue(Repo(cfg))
    if args.all:
        for t in q:
            print(f"{t.id}\t{t.risk}\t{t.data.get('title')}")
    elif q:
        print(q[0].id)
    return 0 if q else 3


def cmd_status(args) -> int:
    cfg = _cfg(args)
    repo = Repo(cfg)
    t = repo.ticket(args.ticket)
    if not args.to:
        print(t.status)
        return 0
    try:
        frm = tickets.set_status(repo, t, args.to, args.as_role, args.reason or "")
    except tickets.TransitionError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EXIT_FAIL
    print(f"{t.id}: {frm} -> {args.to}")
    return 0


def cmd_prompt(args) -> int:
    cfg = _cfg(args)
    extra = Path(args.extra).read_text(encoding="utf-8") if args.extra else ""
    text = prompt.render(cfg, args.play, args.ticket, extra=extra)
    if args.stdout:
        sys.stdout.write(text)
    else:
        print(cfg.rel(prompt.write(cfg, args.play, args.ticket, text)))
    return 0


def cmd_gate(args) -> int:
    from .gate import Gate, pr_tickets, recover

    cfg = _cfg(args)
    if args.play == "pr" and not args.ticket:
        # CI does not know which ticket a PR carries; the branch's changes say so.
        recover(cfg.root)
        found = pr_tickets(cfg, args.base or cfg.section("vcs").get("base", "main"))
        if len(found) > 1:
            print(f"gate pr: this branch moves {len(found)} tickets ({', '.join(found)}); "
                  "a ticket PR carries exactly one", file=sys.stderr)
            return EXIT_FAIL
        args.ticket = found[0] if found else None
        print(f"gate pr: ticket {args.ticket}" if args.ticket else
              "gate pr: no ticket moves on this branch; judging it as a lead PR", flush=True)
    g = Gate(cfg, args.play, args.ticket, args.base, only=args.only.split(",") if args.only else None,
             since=args.since)

    def show(c) -> None:
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "skip"}[c.status]
        print(f"{mark}  {c.name:13} {c.summary}  ({c.ms} ms)", flush=True)
        if c.status == "fail" or args.verbose:
            for d in c.details[-40:]:
                print(f"        {d}")

    ev = g.run(on_check=show)
    if ev.get("config_note"):
        print(f"note: {ev['config_note']}")
        if ev["result"] != "pass" and args.play in ("ci", "pr"):
            # Judging by the base config is deliberate; this is the one case it gets in the way.
            print("note: if this PR fixes a check that is broken on the base branch, the base branch is "
                  "already red: a maintainer merges the config fix with an admin override, and every "
                  "later PR is judged by it. Nothing in the PR itself can switch the config it is judged by.")
    print(f"\ngate {args.play} {args.ticket or ''}: {ev['result'].upper()}  evidence: {ev['path']}")
    return 0 if ev["result"] == "pass" else EXIT_FAIL


def cmd_run(args) -> int:
    from . import run

    cfg = _cfg(args)
    extra = Path(args.extra).read_text(encoding="utf-8") if args.extra else ""
    return run.run(cfg, args.play, args.ticket, args.agent, args.attempts, args.base, extra, args.dry_run)


def cmd_skills(args) -> int:
    cfg = _cfg(args)
    if args.action == "add":
        e = skills.add(cfg, args.spec, name=args.name, ref=args.ref, path=args.path)
        print(f"pinned {args.spec} @ {e['ref'][:12]} sha256 {e['sha256'][:12]}")
        return 0
    if args.action == "catalog":
        for k, v in skills.catalog()["skills"].items():
            print(f"{k:45} {v.get('use', '')}")
        return 0
    probs = skills.verify(cfg)
    for p in probs:
        print(f"ERROR {p}")
    if not probs:
        print("skills ok")
    return EXIT_FAIL if probs else 0


def cmd_adapters(args) -> int:
    cfg = _cfg(args)
    stale = adapters.sync(cfg, check=args.check)
    for s in stale:
        print(("stale: " if args.check else "wrote: ") + s)
    return EXIT_FAIL if (args.check and stale) else 0


def cmd_migrate(args) -> int:
    cfg = _cfg(args)
    total = 0
    repo = Repo(cfg)
    for t in repo.tickets.values():
        n = tickets.migrate_acs(t.path)
        if n:
            print(f"{cfg.rel(t.path)}: numbered {n} acceptance criteria")
        total += n
        # Shipped under v0 (no v1 review): exempt from the v1 review and size rules only.
        try:
            reviewed = repo.review_for(t.id) is not None
        except fm.ParseError:
            reviewed = True  # a malformed v1 review is lint's to report, not a v0 ticket
        if t.status == "done" and not reviewed:
            text = t.path.read_bytes().decode("utf-8")
            marked = tickets.mark_legacy_text(text)
            if marked != text:
                t.path.write_text(marked, encoding="utf-8", newline="")
                print(f"{cfg.rel(t.path)}: marked legacy: v0 (shipped without a v1 review)")
    print(f"{total} acceptance criteria numbered. Tests must now carry tags like T-001-01/AC-1.")
    return 0


def cmd_routes(args) -> int:
    from . import extract

    cfg = _cfg(args)
    from .artifacts import normalize_path

    routes, pages, errs = extract.code_surface(cfg)
    contracts = Repo(cfg).contracts
    code = set(routes) | {f"PAGE {p}" for p in pages}
    declared = {r.key for r in contracts.routes}
    if pages:  # only extractors that report pages can say a page is not built
        declared |= {f"PAGE {normalize_path(p)}" for p in contracts.pages}
    for e in errs:
        print(f"ERROR {e}")
    for k in sorted(code | declared):
        tag = "ok  " if k in code and k in declared else "CODE" if k in code else "TODO"
        print(f"{tag}  {k}")
    print("\nok = declared and built; CODE = built but undeclared (drift); TODO = declared, not built")
    return EXIT_FAIL if code - declared or errs else 0


def cmd_init(args) -> int:
    from .config import KIT_ROOT

    root = Path(args.root or ".").resolve()
    created = []

    def put(rel: str, content: str) -> None:
        p = root / rel
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created.append(rel)

    profile = args.profile
    if profile:
        config.load_profile(profile)  # validate
    put("sdlc.toml", (KIT_ROOT / "templates" / "sdlc.toml").read_text(encoding="utf-8")
        .replace('profile = ""', f'profile = "{profile}"'))
    put("AGENTS.md", (KIT_ROOT / "templates" / "product-AGENTS.md").read_text(encoding="utf-8"))
    for d in ("intent", "design/pages", "arch", "decisions", "tickets", "reviews", "evidence", "ops", "skills/vendor"):
        (root / d).mkdir(parents=True, exist_ok=True)
        keep = root / d / ".gitkeep"
        if not any((root / d).iterdir()):
            keep.write_text("", encoding="utf-8")
    for s in ("frontend-patterns", "backend-patterns"):
        dest = root / "skills" / s
        if not dest.exists():
            shutil.copytree(KIT_ROOT / "skills" / s, dest)
            created.append(f"skills/{s}/")
    put("skills.lock.json", '{\n  "version": 1,\n  "skills": {}\n}\n')
    put(".github/workflows/sdlc.yml", (KIT_ROOT / "adapters" / "github" / "sdlc.yml").read_text(encoding="utf-8"))
    gi = root / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    if ".sdlc-run/" not in lines:
        gi.write_text("\n".join(lines + [".sdlc-run/"]) + "\n", encoding="utf-8")
        created.append(".gitignore (+.sdlc-run/)")
    cfg = config.load(root)
    created += adapters.sync(cfg)
    for c in created:
        print(f"created {c}")
    print("\nnext: fill sdlc.toml [commands], then `sdlc doctor`")
    return 0


JS_RUNNERS = {"npx": ("--no-install", "--no", "-y", "--yes"), "bunx": (), "pnpx": ()}


def _unresolvable(root: Path, cmd: str) -> str:
    """Why the command's program cannot be found from `root`, or '' if it can. Static: it
    looks the program up instead of running it, so doctor stays fast and side-effect free."""
    import shlex

    import re

    try:
        words = [w.strip('"') for w in shlex.split(cmd, posix=os.name != "nt")]
    except ValueError:
        return ""
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words.pop(0)  # VAR=value prefixes
    if not words:
        return ""
    prog, rest = words[0], words[1:]
    if prog in JS_RUNNERS or (prog in ("pnpm", "yarn") and rest[:1] == ["exec"]):
        spec = next((w for w in rest if w != "exec" and not w.startswith("-")), "")
        # jscpd@4.3.0 -> jscpd, @scope/tool@1.2 -> tool (the binary npx runs)
        tool = re.sub(r"(?<=.)@[^/@]*$", "", spec).rsplit("/", 1)[-1]
        if prog == "npx" and ({"-y", "--yes"} & set(rest)):
            return ""  # npx downloads the pinned package when it is not installed
        if tool and not any((root / "node_modules" / ".bin" / (tool + ext)).exists() for ext in ("", ".cmd")):
            return f"{tool} is not installed (no node_modules/.bin/{tool}); run your package manager's install"
        return ""
    rest = [w for w in rest if not w.startswith("-")]  # npm run --silent lint
    if prog in ("npm", "pnpm", "yarn") and rest:
        script = rest[1] if rest[0] == "run" and len(rest) > 1 else rest[0]
        if rest[0] == "run" or script in ("test", "start"):
            pkg = root / "package.json"
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}) if pkg.is_file() else {}
            if script not in scripts:
                return f"package.json has no script {script!r}"
        return ""
    if shutil.which(prog) is None and not (root / prog).exists():
        return f"{prog!r} is not on PATH"
    return ""


def cmd_doctor(args) -> int:
    import subprocess

    cfg = _cfg(args)
    probs, notes = [], []
    if cfg.source is None:
        probs.append("no sdlc.toml (run `sdlc init`)")
    if shutil.which("git") is None:
        probs.append("git not on PATH")
    required = set()
    for play in ("build", "ci"):
        required |= set(cfg.section("gate").get(play, []))
    optional = set(cfg.section("gate").get("optional", []))
    for name in ("lint", "typecheck", "unit", "integration", "e2e", "build", "duplication", "start"):
        need = name in required or (name == "start" and "smoke" in required)
        if not cfg.commands.get(name):
            (probs if need and name not in optional else notes).append(f"commands.{name} is not set")
            continue
        if name in ("unit", "integration", "e2e") and "{junit}" not in cfg.commands[name]:
            probs.append(f"commands.{name} has no {{junit}} placeholder; AC coverage cannot be proven")
        missing = _unresolvable(cfg.root, cfg.commands[name])
        if missing:
            probs.append(f"commands.{name}: {missing}; the check would fail (or never run) as configured")
    if "contracts" in required and not cfg.section("routes").get("extractor"):
        probs.append("routes.extractor is not set; contract drift cannot be checked")
    if not cfg.section("tests").get("globs"):
        probs.append("tests.globs is empty")
    gi = cfg.root / ".gitignore"
    if not gi.is_file() or ".sdlc-run/" not in gi.read_text(encoding="utf-8"):
        probs.append(".sdlc-run/ is not in .gitignore")
    stale = adapters.sync(cfg, check=True)
    if stale:
        notes.append("adapter files out of date: " + ", ".join(stale) + " (run `sdlc adapters sync`)")
    if not (cfg.root / ".github" / "workflows").is_dir():
        notes.append("no .github/workflows: nothing enforces the gate on PRs unless your CI runs `sdlc gate ci`")
    probs += [f"skills: {p}" for p in skills.verify(cfg)]
    if not cfg.section("agents"):
        notes.append("no [agents.*] in sdlc.toml: `sdlc run` is unavailable (see adapters/AGENTS-RUNNER.md)")
    try:
        subprocess.run(["git", "-C", str(cfg.root), "rev-parse"], check=True, capture_output=True)
    except Exception:
        probs.append("not a git repository")
    for n in notes:
        print(f"note  {n}")
    for p in probs:
        print(f"ERROR {p}")
    print("doctor: " + ("OK" if not probs else f"{len(probs)} problem(s)"))
    return EXIT_FAIL if probs else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sdlc", description=__doc__)
    ap.add_argument("--version", action="version", version=f"sdlc {__version__}")
    ap.add_argument("--root", help="product root (default: nearest sdlc.toml)")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("init", help="bootstrap a product repo")
    p.add_argument("--profile", default="", help="stack profile (see profiles/)")
    p.set_defaults(fn=cmd_init)

    p = sp.add_parser("doctor", help="check that the product is wired so gates can't pass vacuously")
    p.set_defaults(fn=cmd_doctor)

    p = sp.add_parser("lint", help="validate specs, plans, contracts, tickets, reviews")
    p.add_argument("ticket", nargs="?")
    p.add_argument("--strict", action="store_true", help="warnings fail too")
    p.set_defaults(fn=cmd_lint)

    p = sp.add_parser("trace", help="requirement -> ticket -> AC -> test matrix")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_trace)

    p = sp.add_parser("next", help="print the next ticket a build agent should take")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_next)

    p = sp.add_parser("status", help="read or move a ticket's status through the state machine")
    p.add_argument("ticket")
    p.add_argument("to", nargs="?")
    p.add_argument("--as", dest="as_role", default="lead",
                   choices=["lead", "build", "test", "review", "merge"])
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_status)

    p = sp.add_parser("prompt", help="assemble the exact prompt for a play")
    p.add_argument("play")
    p.add_argument("ticket", nargs="?")
    p.add_argument("--extra", help="file with extra lead instructions")
    p.add_argument("--stdout", action="store_true")
    p.set_defaults(fn=cmd_prompt)

    p = sp.add_parser("gate", help="run every check for a play; writes evidence")
    p.add_argument("play", choices=["build", "test", "review", "pr", "ci"])
    p.add_argument("ticket", nargs="?")
    p.add_argument("--base", help="base branch (default vcs.base)")
    p.add_argument("--since", help="judge scope on changes after this commit (default: base branch "
                   "for build, the proven build commit for test/review)")
    p.add_argument("--only", help="comma-separated subset of checks (local iteration only)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_gate)

    p = sp.add_parser("run", help="drive an agent through a play with the gate in the loop")
    p.add_argument("play", choices=["build", "test", "review"])
    p.add_argument("ticket")
    p.add_argument("--agent", required=True)
    p.add_argument("--attempts", type=int)
    p.add_argument("--base")
    p.add_argument("--extra")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sp.add_parser("skills", help="vendor third-party skills pinned by commit + hash")
    p.add_argument("action", choices=["add", "verify", "catalog"])
    p.add_argument("spec", nargs="?", help="catalog key or git URL")
    p.add_argument("--name")
    p.add_argument("--ref")
    p.add_argument("--path")
    p.set_defaults(fn=cmd_skills)

    p = sp.add_parser("adapters", help="generate per-tool entry files from AGENTS.md")
    p.add_argument("action", choices=["sync"])
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_adapters)

    p = sp.add_parser("migrate", help="upgrade legacy tickets (number acceptance criteria)")
    p.set_defaults(fn=cmd_migrate)

    p = sp.add_parser("routes", help="compare routes in code with CONTRACTS")
    p.set_defaults(fn=cmd_routes)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "skills" and args.action == "add" and not args.spec:
        raise SystemExit("skills add needs a catalog key or git URL")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
