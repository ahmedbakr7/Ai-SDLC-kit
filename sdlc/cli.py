"""sdlc: deterministic conveyor for the ai-sdlc kit. Python >= 3.11, stdlib only."""
from __future__ import annotations

import argparse
import os
import json
import shutil
import sys
from pathlib import Path

from . import __version__, adapters, config, fm, gitutil, lint, presets, prompt, skills, tickets, trace
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
    from . import baseline, waivers

    cfg = _cfg(args)
    m = trace.matrix(Repo(cfg))
    probs = trace.problems(m)
    # Problems sdlc-baseline.json lists are known debt; new ones fail, and so do entries that
    # stopped failing (prune them), so the baseline only shrinks. Waivers on the base branch
    # cover their count of what is left; one that covers nothing is stale.
    bl = baseline.path(cfg.root, cfg.data["paths"])
    known = baseline.load(cfg.root, cfg.rel(bl)).get("trace", [])
    new, stale = baseline.compare(known, probs)
    wrel = cfg.rel(waivers.path(cfg.root, cfg.data["paths"]))
    try:
        wbase: str | None = gitutil.merge_base(cfg.root, cfg.section("vcs").get("base", "main"))
    except gitutil.GitError:
        wbase = None
    ws = waivers.state(cfg.root, wrel, wbase, waivers.max_days(cfg.section("waivers")),
                       renewals=not presets.hardened(cfg.data)).for_check("trace")
    new, covered, unused = waivers.apply(ws, new)
    if args.json:
        from collections import Counter

        known_now = Counter(probs) - Counter(new) - Counter(k for k, _ in covered)
        print(json.dumps({"matrix": m, "problems": new, "known": sorted(known_now.elements()),
                          "fixed": stale, "waived": [f"{k}: {w.label()}" for k, w in covered],
                          "stale_waivers": [w.id for w in unused]}, indent=2))
    else:
        print(trace.render(m))
        for p in new:
            print(f"ERROR {p}")
        for p in stale:
            print(f"ERROR fixed, still in {cfg.rel(bl)}: {p}; run `sdlc baseline --prune`")
        for w in unused:
            print(f"ERROR waiver {w.id} covers nothing; remove it from {wrel}")
        for k, w in covered:
            print(f"WAIVED {k}: {w.label()}")
        if known and not new and not stale:
            print(f"BASELINED: {len(probs) - len(covered)} known trace problem(s) from {cfg.rel(bl)}, none new")
    return EXIT_FAIL if new or stale or unused else 0


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
        print(repo.status_of(t))
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
        # Which tickets a PR serves is read the way the base branch's config says (trailers when
        # status is derived), so a PR cannot change how it is found.
        found = pr_tickets(Gate(cfg, "pr", None, args.base).cfg, args.base or cfg.section("vcs").get("base", "main"))
        if len(found) > 1:
            print(f"gate pr: this branch moves {len(found)} tickets ({', '.join(found)}); "
                  "a ticket PR carries exactly one", file=sys.stderr)
            return EXIT_FAIL
        args.ticket = found[0] if found else None
        print(f"gate pr: ticket {args.ticket}" if args.ticket else
              "gate pr: no ticket moves on this branch; judging it as a lead PR", flush=True)
    g = Gate(cfg, args.play, args.ticket, args.base, only=args.only.split(",") if args.only else None,
             since=args.since, lane=args.lane)

    def show(c) -> None:
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "skip"}[c.status]
        print(f"{mark}  {c.name:13} {c.summary}  ({c.ms} ms)", flush=True)
        if c.status == "fail" or args.verbose:
            for d in c.details[-40:]:
                print(f"        {d}")
        else:  # a waived failure is never silent: its owner and expiry show on every run
            for d in [d for d in c.details if d.startswith(("waived: ", "WARN ", "pending: "))][-40:]:
                print(f"        {d}")

    ev = g.run(on_check=show)
    if ev.get("config_note"):
        print(f"note: {ev['config_note']}")
        if ev["result"] != "pass" and args.play in ("ci", "pr"):
            # Judging by the base config is deliberate; this is the one case it gets in the way.
            print("note: if this PR fixes a check that is broken on the base branch, the base branch is "
                  "already red: a maintainer merges the config fix with an admin override, and every "
                  "later PR is judged by it. Nothing in the PR itself can switch the config it is judged by.")
    if ev.get("dirty") and args.play in ("build", "test", "review"):
        # The evidence names HEAD, which does not hold the uncommitted changes the checks saw.
        print(f"note: the tree has uncommitted changes, so this run proves no commit ({ev['commit'][:7]} does "
              "not hold them). Commit, then run the gate again.")
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
    from . import approval

    cfg = _cfg(args)
    total = 0
    repo = Repo(cfg)
    if args.areas or approval.records_mode(cfg):
        for t in repo.tickets.values():
            text = t.path.read_bytes().decode("utf-8")
            new = tickets.migrate_v2_text(text, areas=args.areas, derived=approval.records_mode(cfg))
            if new != text:
                t.path.write_text(new, encoding="utf-8", newline="")
                print(f"{cfg.rel(t.path)}: " + ("files: -> areas:; " if args.areas else "")
                      + "delivery status rewritten for derived status" * approval.records_mode(cfg))
        repo = Repo(cfg)
        if approval.records_mode(cfg):
            return 0  # reviews/ and evidence/ stay as read-only history; v0 marking is a file-mode concern
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


def cmd_approval(args) -> int:
    """CI's `sdlc/approval` check: an approval covers the PR's head for every role its lane needs."""
    from . import approval, gitutil
    from .gate import Gate, pr_tickets

    branch_cfg = _cfg(args)
    if not args.base and approval.pr_number(args.pr) and os.environ.get("GITHUB_REPOSITORY"):
        # A comment event carries no base: the PR says which branch it targets. The branch's
        # sdlc.toml is the PR's to write, so it decides neither this lookup nor where the token goes.
        try:
            target = (approval.forge_client(None).get(f"/pulls/{approval.pr_number(args.pr)}") or {})
            ref = (target.get("base") or {}).get("ref", "")
            args.base = f"origin/{ref}" if ref else None
        except Exception:
            pass
    base = args.base or branch_cfg.section("vcs").get("base", "main")
    # Judged by the base branch's sdlc.toml, like every gate: a PR cannot switch its own
    # approval mode, roles or trust setting.
    cfg = Gate(branch_cfg, "pr", None, args.base).cfg
    m = approval.mode(cfg)
    if m == "file":
        print("approval: [approval] mode is file; reviews/<id>.md is checked by `sdlc gate pr`")
        return 0
    found = [args.ticket] if args.ticket else pr_tickets(cfg, base)
    if len(found) > 1:
        print(f"approval: this branch serves {len(found)} tickets ({', '.join(found)}); a ticket PR serves one",
              file=sys.stderr)
        return EXIT_FAIL
    g = Gate(branch_cfg, "pr", found[0] if found else None, args.base)
    head = gitutil.head(cfg.root)
    pr = None
    if m == "forge":
        n = approval.pr_number(args.pr)
        if not n:
            print("approval: no PR number (pass --pr, or run on a pull_request event)", file=sys.stderr)
            return EXIT_FAIL
        pr, records = approval.forge_records(approval.forge_client(cfg), n)
        if pr.head and not head.startswith(pr.head[:12]) and pr.head != head:
            # A merge-ref checkout (refs/pull/N/merge) is not the PR head: judge the PR head.
            head = pr.head
    else:
        if approval.notes_missing(cfg):
            print(f"approval: {approval.NOTES_REF} is missing; fetch it "
                  f"(git fetch origin {approval.NOTES_REF}:{approval.NOTES_REF})", file=sys.stderr)
            return EXIT_FAIL
        mb = gitutil.merge_base(cfg.root, base)
        shas = gitutil.git(cfg.root, "rev-list", f"{mb}..{head}", check=False).split()
        records = approval.git_records(cfg, shas, base)
    res = approval.evaluate(cfg, g, records, pr, head)
    out = {"result": "pass" if res.ok else "fail", "summary": res.summary, "details": res.details,
           "trust_based": res.trust_based, "head": head, "ticket": found[0] if found else None}
    dest = cfg.root / ".sdlc-run" / "approval.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for d in res.details:
        print(f"  {d}")
    print(f"approval: {'PASS' if res.ok else 'FAIL'}  {res.summary}")
    if args.publish_status and m == "forge":
        # A comment-triggered run's check lands on the default branch, not the PR: the result
        # is posted as a commit status on the PR head, which branch protection requires.
        approval.forge_client(cfg).post(f"/statuses/{head}", {
            "state": "success" if res.ok else "failure", "context": "sdlc/approval",
            "description": res.summary[:140]})
    return 0 if res.ok else EXIT_FAIL


def cmd_review(args) -> int:
    """Publish the review agent's record (.sdlc-run/review-<id>.md): a PR comment in forge mode,
    a note on the reviewed commit in git mode. Agents never need forge credentials."""
    from . import approval, gitutil

    cfg = _cfg(args)
    p = cfg.root / ".sdlc-run" / f"review-{args.ticket}.md"
    if not p.is_file():
        raise SystemExit(f"no review record at {cfg.rel(p)}; run the review play first")
    text = p.read_text(encoding="utf-8")
    d = approval.parse(text)
    if d is None or str(d.get("ticket", "")) != args.ticket:
        raise SystemExit(f"{cfg.rel(p)} is not an approval record for {args.ticket}")
    m = approval.mode(cfg)
    if m == "forge":
        n = approval.pr_number(args.pr)
        if not n:
            raise SystemExit("review publish: pass --pr N")
        res = approval.forge_client(cfg).post(f"/issues/{n}/comments", {"body": text})
        print(f"published to PR #{n}: {res.get('html_url', '')}")
    elif m == "git":
        gitutil.git(cfg.root, "notes", "--ref", approval.NOTES_REF, "add", "-f", "-F", str(p), str(d.get("commit")))
        print(f"noted on {str(d.get('commit'))[:12]} in {approval.NOTES_REF}; "
              f"push it: git push origin {approval.NOTES_REF}")
    else:
        raise SystemExit("review publish needs [approval] mode = forge or git")
    return 0


def cmd_followups(args) -> int:
    """Turn the [follow-up] findings of a merged PR's approvals into draft tickets."""
    from . import approval

    cfg = _cfg(args)
    if approval.mode(cfg) != "forge":
        raise SystemExit("followups reads PR approvals: [approval] mode = forge")
    _, records = approval.forge_records(approval.forge_client(cfg), args.pr)
    repo = Repo(cfg)
    made = 0
    for rec in records:
        if rec.verdict != "approve" or not rec.ticket or rec.ticket not in repo.tickets:
            continue
        for line in lint._section(rec.body, "## Findings").splitlines():
            if "[follow-up]" not in line:
                continue
            made += 1
            src = repo.tickets[rec.ticket]
            nid = tickets.next_id(repo, src.id)
            text = tickets.followup_text(src, nid, line.strip().lstrip("-* ").replace("[follow-up]", "").strip(),
                                         f"PR #{args.pr}")
            dest = src.path.parent / f"{nid}-follow-up.md"
            dest.write_text(text, encoding="utf-8")
            repo = Repo(cfg)
            print(f"{cfg.rel(dest)}: draft follow-up from {rec.ticket}")
    print(f"{made} follow-up ticket(s) drafted; the lead edits and makes them ready in a lead PR")
    return 0


def cmd_commit(args) -> int:
    """`git commit` with the trailers `sdlc run` writes: Sdlc-Agent and Sdlc-Play, which the
    independent-reviewer rule reads, and Sdlc-Ticket, which derived status reads."""
    from . import gitutil

    cfg = _cfg(args)
    Repo(cfg).ticket(args.ticket)
    # --trailer joins the message's own trailer block (Co-Authored-By, ...). A separate
    # paragraph would end git's trailer block above it, so those lines stop being trailers.
    gitutil.git(cfg.root, "commit", "-q", "-m", args.message, "--trailer", f"Sdlc-Agent: {args.agent}",
                "--trailer", f"Sdlc-Play: {args.play}", "--trailer", f"Sdlc-Ticket: {args.ticket}")
    print(gitutil.head(cfg.root))
    return 0


def cmd_baseline(args) -> int:
    """Record the failures a red base branch already has (sdlc-baseline.json), or with
    --prune drop the ones that stopped failing. It never adds to an existing baseline."""
    from collections import Counter

    from . import baseline
    from .gate import Gate

    cfg = _cfg(args)
    p = baseline.path(cfg.root, cfg.data["paths"])
    if p.exists() and not args.prune:
        print(f"{cfg.rel(p)} exists and may only shrink: use `sdlc baseline --prune`", file=sys.stderr)
        return EXIT_FAIL
    if args.prune and not p.exists():
        print(f"no {cfg.rel(p)} to prune", file=sys.stderr)
        return EXIT_FAIL
    g = Gate(cfg, "ci", None, args.base, ignore_baseline=True)
    g.run(on_check=lambda c: print(f"{c.status.upper():4}  {c.name}", flush=True))
    now = {c.name: g.findings(c) for c in g.checks if c.name in baseline.BASELINE_CHECKS and c.status == "fail"}
    if probs := trace.problems(trace.matrix(Repo(cfg))):
        now["trace"] = probs
    kept: dict[str, str] = {}
    if args.prune:
        old = baseline.load(cfg.root, cfg.rel(p))  # paths moved since are written renamed
        # Only a check that ran and named its failures proves which entries stopped failing.
        # One that was skipped, or failed as a whole (it crashed, or wrote no results), proves
        # nothing: Hangout's prune dropped 241 ac-coverage entries when its JUnit was missing.
        ran = {c.name: c for c in g.checks}
        for n in old:
            c = ran.get(n)
            if n == "trace":
                continue
            if c is None or c.status == "skip":
                kept[n] = "it did not run"
            elif c.status == "fail" and now.get(n) == [baseline.whole(n)] and old[n] != [baseline.whole(n)]:
                kept[n] = f"it failed as a whole ({c.summary})"
        now = {n: sorted((Counter(v) & Counter(now.get(n, []))).elements()) if n not in kept else v
               for n, v in old.items()}
        # A test suite proves a known failure fixed only by reporting that test as passed. One
        # missing from the JUnit (a file that failed to import, a filter) or skipped proves nothing.
        from .gate import JUNIT_CHECKS
        unseen: dict[str, int] = {}
        for n in JUNIT_CHECKS:
            if n not in old or n in kept:
                continue
            passed = Counter(tc.name for tc in g.testcases if tc.source == n and tc.status == "passed")
            # Counts, since names repeat. "<check>: fails" names no test: it goes once the suite
            # no longer fails as a whole, never kept alive by the absence of a test of that name.
            back = sorted(k for k in (Counter(old[n]) - Counter(now[n]) - passed).elements()
                          if k != baseline.whole(n))
            if back:
                unseen[n] = len(back)
                now[n] = sorted(now[n] + back)
    try:
        text = baseline.dump(now)
    except ValueError as e:  # nothing written: the file stays as it was
        print(f"cannot write {cfg.rel(p)}: {e}", file=sys.stderr)
        return EXIT_FAIL
    p.write_text(text, encoding="utf-8", newline="\n")
    if args.prune:
        removed = sum(len(v) for v in old.values()) - sum(len(v) for v in now.values())
        # A key counts each time it fails ("pruned 14" was 7 keys failing twice each): say both.
        keys = sum(len(Counter(v) - Counter(now.get(n, []))) for n, v in old.items())
        print(f"{cfg.rel(p)}: pruned {removed} failure(s) across {keys} key(s) that no longer fail")
        for n, why in kept.items():
            print(f"kept all {len(old[n])} known {n} failure(s): {why}, so this run cannot tell which "
                  f"still fail; fix the check and prune again", file=sys.stderr)
        for n, k in unseen.items():
            print(f"kept {k} known {n} failure(s) whose tests the JUnit did not report as passed "
                  f"(missing or skipped); run them and prune again", file=sys.stderr)
        return 0
    total = sum(len(v) for v in now.values())
    print(f"{cfg.rel(p)}: {total} known failure(s) in {len(now)} check(s). Commit it in a lead PR; "
          "from then on gates fail only on new failures, and it may only shrink.")
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
    for wf in ("sdlc-approval.yml", "sdlc-approval-review.yml"):
        put(f".github/workflows/{wf}", (KIT_ROOT / "adapters" / "github" / wf).read_text(encoding="utf-8"))
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
    from .gate import real_stack_suites

    suites = real_stack_suites(cfg)
    if suites and not any(cfg.commands.get(k) for k in suites):
        probs.append(f"no real-stack suite: tests.real_stack is {', '.join(suites)}, but "
                     f"commands.{'/'.join(suites)} is not set; routes and pages are never proven over the "
                     "real stack. Configure one, or set tests.real_stack = [] to accept unit-only proof")
    probs += lane_floor_problems(cfg)
    probs += cfg.preset_problems  # the preset forbids them; the stricter value applies meanwhile
    probs += approval_problems(cfg)
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
    notes += _waiver_notes(cfg)
    if not cfg.section("agents"):
        notes.append("no [agents.*] in sdlc.toml: `sdlc run` is unavailable (see adapters/AGENTS-RUNNER.md)")
    try:
        subprocess.run(["git", "-C", str(cfg.root), "rev-parse"], check=True, capture_output=True)
    except Exception:
        probs.append("not a git repository")
    for n in notes:
        print(f"note  {n}")
    for line in presets.resolved(cfg.data):  # what the preset and overrides add up to
        print(f"      {line}")
    for p in probs:
        print(f"ERROR {p}")
    print("doctor: " + ("OK" if not probs else f"{len(probs)} problem(s)"))
    return EXIT_FAIL if probs else 0


def _waiver_notes(cfg: config.Config) -> list[str]:
    """Waiver problems and the 14-day expiry warning. Notes: `gate ci` fails on them, while a
    ticket PR, which runs doctor too, must not."""
    from . import waivers

    rel = cfg.rel(waivers.path(cfg.root, cfg.data["paths"]))
    try:
        ref: str | None = gitutil.merge_base(cfg.root, cfg.section("vcs").get("base", "main"))
    except gitutil.GitError:
        ref = None
    s = waivers.state(cfg.root, rel, ref, waivers.max_days(cfg.section("waivers")),
                      renewals=not presets.hardened(cfg.data))
    return [f"waiver: {p}" for p in s.problems] + [f"waiver: {w}" for w in s.warnings]


# The checks a lane may never drop (ADR-0001): the floor `doctor` holds every product to.
MECHANICAL_FLOOR = ("artifacts", "scope", "immutable", "mechanical", "contracts", "lint", "typecheck", "unit",
                    "ac-coverage", "test-quality", "build")


# What `gate ci` itself may never drop: it proves every shipped AC on main, and the mechanical
# lane's floor is defined by it.
CI_FLOOR = ("artifacts", "immutable", "contracts", "lint", "typecheck", "unit", "ac-coverage", "test-quality", "build")


def lane_floor_problems(cfg: config.Config) -> list[str]:
    g = cfg.section("gate")
    out = []
    suites = [k for k in ("integration", "e2e") if cfg.commands.get(k)]
    missing = [n for n in (*CI_FLOOR, *suites) if n not in g.get("ci", [])]
    if missing:
        out.append(f"gate.ci drops {', '.join(missing)}: gate ci must run every configured test suite and the checks "
                   "that prove shipped ACs on the base branch")
    missing = [n for n in (*MECHANICAL_FLOOR, *suites) if n not in g.get("mechanical", [])]
    if missing:
        out.append(f"gate.mechanical drops {', '.join(missing)}: the mechanical lane must run every check gate ci "
                   "runs (every configured test suite included) plus `mechanical`")
    if "ac-red" not in g.get("build", []):
        out.append("gate.build drops ac-red: the standard lane proves each AC red")
    missing = [n for n in ("artifacts", "scope", "immutable", "spike") if n not in g.get("spike", [])]
    if missing:
        out.append(f"gate.spike drops {', '.join(missing)}: a spike's build must prove it changed documents only")
    if "contract-diff" not in g.get("strict", []):
        out.append("gate.strict drops contract-diff: the strict lane publishes the contract diff")
    return out


def approval_problems(cfg: config.Config) -> list[str]:
    """An approval check that could pass on nobody's say-so is a vacuous gate."""
    from . import approval

    a = cfg.section("approval")
    m = str(a.get("mode", "file"))
    if m not in approval.MODES:
        return [f"approval.mode must be one of {', '.join(approval.MODES)}, got {m!r}"]
    trust = bool(a.get("trust_unsigned", False))
    out = []
    if m == "forge" and not trust and not a.get("reviewers"):
        out.append("approval.mode = forge with no [approval] reviewers: no approval could count (list the "
                   "reviewer identities, or set trust_unsigned = true for trust-based approvals)")
    if m == "git" and not trust and not a.get("allowed_signers"):
        out.append("approval.mode = git with no [approval] allowed_signers: no note could count")
    if trust and m != "file":
        print(f"note  [approval] trust_unsigned = true: approvals are trust-based (identities not verified)")
    return out


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
    p.add_argument("--lane", default="", choices=["", "mechanical", "standard", "strict"],
                   help="raise the ticket's lane (never lowers it)")
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
    p.add_argument("--areas", action="store_true", help="rename files: to areas:")
    p.set_defaults(fn=cmd_migrate)

    p = sp.add_parser("approval", help="CI: does an approval cover this PR's head for its lane?")
    p.add_argument("ticket", nargs="?")
    p.add_argument("--pr", type=int, help="PR number (default: the GitHub event's)")
    p.add_argument("--base", help="base branch (default vcs.base)")
    p.add_argument("--publish-status", action="store_true",
                   help="forge: post the result as the sdlc/approval commit status on the PR head")
    p.set_defaults(fn=cmd_approval)

    p = sp.add_parser("review", help="publish a review record (forge comment or git note)")
    p.add_argument("action", choices=["publish"])
    p.add_argument("ticket")
    p.add_argument("--pr", type=int)
    p.set_defaults(fn=cmd_review)

    p = sp.add_parser("followups", help="draft tickets from a PR approval's [follow-up] findings")
    p.add_argument("--pr", type=int, required=True)
    p.set_defaults(fn=cmd_followups)

    p = sp.add_parser("commit", help="git commit with the Sdlc-Agent, Sdlc-Play and Sdlc-Ticket trailers")
    p.add_argument("ticket")
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--agent", required=True, help="the agent that made the change (a reviewer must be another)")
    p.add_argument("--play", required=True, choices=["build", "test"])
    p.set_defaults(fn=cmd_commit)

    p = sp.add_parser("baseline", help="record a red base branch's known failures (or --prune fixed ones)")
    p.add_argument("--prune", action="store_true", help="drop entries that no longer fail; never adds")
    p.add_argument("--base", help="base branch (default: vcs.base)")
    p.set_defaults(fn=cmd_baseline)

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
