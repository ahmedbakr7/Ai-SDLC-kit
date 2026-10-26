"""`sdlc plan <ticket>` (ADR-0006): what the gate will demand of a ticket, before any build.

Nothing here predicts. Each answer comes from the function the gate itself calls: the check
lists from Gate.plan(), the write sets from Gate.allowed(), the lane raises from
lanes.TRIGGERS (the table lanes.resolve raises through), the real-stack rule from
Ticket.owes_real_stack. What only a diff can decide (which lane the diff resolves to, which
files land outside the areas) is named as decided at build time, not guessed.
"""
from __future__ import annotations

from . import config, lanes
from .artifacts import Ticket
from .config import Config

PLAYS = ("build", "test", "review", "pr")
_GLOB_CHARS = set("*?[")


def problems(cfg: Config, t: Ticket) -> list[str]:
    """Ways a ticket's build is certain to fail, readable from the ticket and config alone.
    Exact, never heuristic: each one is a rule the gate enforces with no exception."""
    from . import baseline
    from .gate import _glob, hard_reason, real_stack_suites

    out = []
    p = cfg.data["paths"]
    # In _scope's order: its own ticket (amendments) and the bookkeeping also in the build's write
    # set (the baseline it may prune, its own build evidence) pass first; then a test ticket may
    # change tests only; then the contracts pass (they raise the lane to strict); then hard_reason.
    exempt = {cfg.rel(t.path), cfg.rel(baseline.path(cfg.root, p)), f"{p['evidence']}/{t.id}.build.json"}
    tests = [*cfg.section("tests").get("globs", []), *cfg.section("tests").get("integration_globs", [])]
    for f in dict.fromkeys([*t.files, *t.shared, *t.areas]):
        if set(f) & _GLOB_CHARS or f in exempt:  # a glob is judged per file it matches
            continue
        if t.type == "test" and not any(_glob(f, g) for g in tests):
            out.append(f"lists {f}, but a test ticket changes tests only (tests.globs, tests.integration_globs)")
            continue
        why = "" if f == p["contracts"] else hard_reason(cfg, f, "build", t)
        if why:
            out.append(f"lists {f}, but the build may never change it: {why}")
    suites = real_stack_suites(cfg)
    # ac-coverage in a play that proves the ticket demands the real-stack tag: the test play (a
    # test ticket's build), and in records mode the PR too, which runs the build and test lists.
    from .approval import records_mode

    g = cfg.section("gate")
    proving = ["build" if t.type == "test" else "test"] + (["build", "test"] if records_mode(cfg) else [])
    if (t.owes_real_stack() and suites and any("ac-coverage" in g.get(x, []) for x in proving)
            and not any(cfg.commands.get(s) for s in suites)):
        out.append(f"owes real-stack proof, but no tests.real_stack suite ({', '.join(suites)}) has a command; "
                   "configure one, or the lead sets tests.real_stack = [] or the ticket's test: none")
    unit = cfg.commands.get("unit", "")
    if t.lane == "refactor" and "{junit}" not in unit:
        out.append("declares the refactor lane, which needs a unit command with {junit} "
                   "(it runs the AC tests on the base)")
    return out


def build(cfg: Config, ticket_id: str, base: str | None = None) -> dict:
    """The gate's plan for a ticket as JSON-ready data."""
    from .gate import PR_ROLES, Gate, real_stack_suites

    g = Gate(cfg, "build", ticket_id, base, read_only=True)
    cfg, t = g.cfg, g.ticket  # the gate's config: the base branch's, as every ticket gate uses
    declared = t.lane
    raises = lanes.raises(declared)
    names = [declared] + sorted({to for _, to in raises}, key=lanes.rank)
    gate_lists = cfg.section("gate")
    suites = real_stack_suites(cfg)
    out_lanes = []
    for name in names:
        g.lane = lanes.Lane(name, declared)
        plays: dict[str, dict | None] = {}
        for play in PLAYS:
            if play == "test" and not (t.test_play and name not in lanes.NO_TEST_PLAY):
                plays[play] = None
                continue
            if play not in gate_lists and play != "pr":
                continue
            g.play = play
            try:
                checks = g.plan()
            except SystemExit:
                continue
            globs, exact = g.allowed(PR_ROLES if play == "pr" else (play,))
            plays[play] = {"checks": checks, "may_write": {"globs": list(globs), "paths": sorted(exact)}}
        g.play = "build"
        ran = {c for p in plays.values() if p for c in p["checks"]}
        build_checks = set(plays["build"]["checks"]) if plays.get("build") else set()
        owes = t.owes_real_stack(name) and bool(suites)
        proof = {
            "passing_tagged_test": "ac-coverage" in ran,
            "red_on_base": "ac-red" in build_checks,
            "passes_on_base": "refactor" in build_checks,
            "real_stack": list(suites) if owes else [],
        }
        out_lanes.append({"lane": name, "declared": name == declared, "plays": plays, "ac_proof": proof,
                          "no_test_play": (None if plays.get("test") is not None else
                                           ("the whole suite is the proof (ADR-0004)" if name in lanes.NO_TEST_PLAY
                                            else t.no_test_play_reason))})
    return {
        "ticket": t.id,
        "title": str(t.data.get("title", "")),
        "type": t.type,
        "declared_lane": declared,
        "lane_source": _lane_source(t),
        "config": g.config_note or f"judged by {g.base}'s {config.CONFIG_NAME}",
        "acceptance_criteria": [{"tag": f"{t.id}/{ac}", "text": text} for ac, text in t.acs if ac],
        "raises": [{"trigger": tr.id, "to": to, "when": tr.describe(cfg)} for tr, to in raises],
        "lanes": out_lanes,
        "real_stack_suites": {s: bool(cfg.commands.get(s)) for s in suites},
        "decided_at_build": [
            "the lane the diff resolves to (any raise above can fire)",
            "files outside the ticket's areas (a flag the approving review must name, not a failure)",
            "whether ac-red has production files to revert",
        ],
        "problems": problems(cfg, t),
        "areas_note": ("" if g.build_areas() == (t.areas + t.shared, t.files) else
                       f"this branch changes the ticket's areas; the build's write set above is {g.base}'s "
                       "(widening is free, but files outside the base areas stay flags the review must name), "
                       "while CANNOT PASS judges the ticket as written here"),
    }


def _lane_source(t: Ticket) -> str:
    if t.risk == "high":
        return "risk: high makes it strict"
    if t.type == "contract":
        return "type: contract makes it strict"
    if str(t.data.get("lane", "") or "") in lanes.LANES:
        return "the ticket's lane field"
    return "default: the ticket sets no lane"


def render(p: dict) -> str:
    lines = [f"{p['ticket']}: {p['title']}" if p["title"] else p["ticket"],
             f"lane: {p['declared_lane']} ({p['lane_source']})",
             f"config: {p['config']}"]
    if p["areas_note"]:
        lines.append(f"note: {p['areas_note']}")
    if p["problems"]:
        lines.append("")
        lines.append("CANNOT PASS as written:")
        lines += [f"  - {x}" for x in p["problems"]]
    acs = p["acceptance_criteria"]
    lines.append("")
    lines.append("acceptance criteria: " + (", ".join(a["tag"] for a in acs) if acs else "none"))
    base = p["lanes"][0]
    lines.append("")
    lines.append(f"in the {base['lane']} lane (declared):")
    lines += _lane_lines(base, acs)
    if p["raises"]:
        lines.append("")
        lines.append("the diff can raise the lane (decided at build time):")
        for r in p["raises"]:
            lines.append(f"  -> {r['to']}: {r['when']}  [{r['trigger']}]")
    for ln in p["lanes"][1:]:
        lines.append("")
        lines.append(f"if raised to {ln['lane']}, compared with {base['lane']}:")
        lines += _diff_lines(base, ln, acs)
    suites = p["real_stack_suites"]
    if suites:
        lines.append("")
        lines.append("real-stack suites: " + ", ".join(f"{s} ({'configured' if ok else 'no command'})"
                                                     for s, ok in suites.items()))
    lines.append("")
    lines.append("decided at build time, not here:")
    lines += [f"  - {x}" for x in p["decided_at_build"]]
    return "\n".join(lines)


def _lane_lines(ln: dict, acs: list) -> list[str]:
    out = []
    for play, d in ln["plays"].items():
        if d is None:
            out.append(f"  {play:6} no test play: {ln['no_test_play']}")
            continue
        out.append(f"  {play:6} checks: {', '.join(d['checks']) or '(none)'}")
        w = d["may_write"]
        out.append(f"  {'':6} may write: {', '.join(dict.fromkeys(w['globs'] + w['paths'])) or '(nothing)'}")
    if acs:
        out.append(f"  each AC owes: {_proof_words(ln['ac_proof'])}")
    return out


def _diff_lines(base: dict, ln: dict, acs: list) -> list[str]:
    out = []
    for play in PLAYS:
        a, b = base["plays"].get(play), ln["plays"].get(play)
        if a == b:
            continue
        if b is None:
            out.append(f"  {play:6} no test play: {ln['no_test_play']}")
            continue
        if a is None:
            out.append(f"  {play:6} checks: {', '.join(b['checks'])}")
            continue
        added = [c for c in b["checks"] if c not in a["checks"]]
        dropped = [c for c in a["checks"] if c not in b["checks"]]
        if added or dropped:
            out.append(f"  {play:6} " + "; ".join(x for x in (
                f"adds {', '.join(added)}" if added else "", f"drops {', '.join(dropped)}" if dropped else "") if x))
    if acs and ln["ac_proof"] != base["ac_proof"]:
        out.append(f"  each AC owes: {_proof_words(ln['ac_proof'])}")
    if not out:
        out.append("  the same checks and proof")
    return out


def _proof_words(proof: dict) -> str:
    parts = []
    if proof["passing_tagged_test"]:
        parts.append("a passing test named with its tag")
    if proof["red_on_base"]:
        parts.append("a tagged test that fails with the ticket's production files put back to the base (ac-red)")
    if proof["passes_on_base"]:
        parts.append("tagged tests that also pass on the base (refactor: behaviour unchanged)")
    if proof["real_stack"]:
        parts.append(f"a passing {'/'.join(proof['real_stack'])} test carrying the tag")
    return "; ".join(parts) or "nothing the gate checks"
