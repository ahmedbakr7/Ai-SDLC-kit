"""ADR-0006: `sdlc plan` prints what the gate will demand of a ticket, from the gate's own
functions, and `sdlc lint` warns about builds that are certain to fail. Each rule has a test
that catches the defect it exists for and one that shows the reference passes."""
import ast
import inspect
import json
import textwrap
import unittest

from helpers import ProductRepo, git
from sdlc import config, lanes, plan
from sdlc.gate import Gate

TICKET = """---
id: T-042-09
title: Plan probe
type: backend
status: ready
risk: low
{lane}depends_on: []
areas:
{areas}
shared: []
skills:
  - build
{extra}requirements:
  - F-042-1
acceptance_criteria:
  - "AC-1: the probe answers 200"
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
---

A ticket for the plan tests.
"""
PATH = "tickets/T-042-09-plan-probe.md"


def ticket(lane: str = "", areas: tuple[str, ...] = ("app/returns.py",), extra: str = "") -> str:
    return TICKET.format(lane=f"lane: {lane}\n" if lane else "",
                         areas="\n".join(f"  - {a}" for a in areas), extra=extra)


class Triggers(unittest.TestCase):
    def test_every_raise_in_resolve_names_a_table_trigger_and_every_trigger_is_raised(self) -> None:
        tree = ast.parse(textwrap.dedent(inspect.getsource(lanes.resolve)))
        calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "raise_to"]
        self.assertTrue(calls)
        self.assertTrue(all(c.args and isinstance(c.args[0], ast.Constant) for c in calls),
                        "every raise_to names its trigger as a literal")
        self.assertEqual({c.args[0].value for c in calls}, {t.id for t in lanes.TRIGGERS})

    def test_raises_by_declared_lane(self) -> None:
        def pairs(declared: str) -> set[tuple[str, str]]:
            return {(t.id, to) for t, to in lanes.raises(declared)}

        self.assertEqual(pairs("strict"), set())
        std = pairs("standard")
        self.assertEqual(std, {("override", "strict"), ("contracts", "strict"), ("waivers", "strict"),
                               ("strict-paths", "strict")})
        mech = pairs("mechanical")
        for tid in ("no-merge-base", "transforms", "ac-changed", "residue", "override-refactor"):
            self.assertIn((tid, "standard"), mech)
        self.assertNotIn(("override", "refactor"), mech, "only the lead's declaration puts a PR in refactor")
        ref = pairs("refactor")
        self.assertFalse({tid for tid, _ in ref} & {"residue", "ac-changed", "transforms", "no-merge-base"},
                         "the transform replay applies to mechanical tickets only")
        self.assertIn(("contracts", "strict"), ref)


class TriggersAgreeWithResolve(unittest.TestCase):
    """Every raise lanes.raises() lists can fire in lanes.resolve, and every raise resolve makes
    is listed: run resolve over each declared lane, override and diff that needs no replay."""

    def test_both_directions(self) -> None:
        from pathlib import Path
        from sdlc.artifacts import Ticket

        p = ProductRepo()
        try:
            cfg = config.load(p.root)
            pc = cfg.data["paths"]
            diffs = [[], [pc["contracts"]], [pc.get("waivers", "sdlc-waivers.toml")], ["db/migrations/001.sql"]]
            replay = {"transforms", "ac-changed", "residue"}  # need a merge base; covered in test_lanes
            for declared in lanes.LANES:
                t = Ticket("T-042-09", Path(p.root / PATH), {"lane": declared, "type": "backend"}, "")
                seen = set()
                for override in ["", *lanes.LANES]:
                    for changed in diffs:
                        ln = lanes.resolve(cfg, t, changed, None, override=override)
                        for tid, why in zip(ln.triggers, ln.reasons):
                            seen.add((tid, why.split(":", 1)[0].split(" -> ")[1]))
                listed = {(tr.id, to) for tr, to in lanes.raises(declared)}
                self.assertEqual(seen - listed, set(), f"{declared}: resolve raises what plan does not list")
                self.assertEqual({x for x in listed if x[0] not in replay} - seen, set(),
                                 f"{declared}: plan lists a raise resolve never makes")
        finally:
            p.close()


class PlanAgreesWithGate(unittest.TestCase):
    """The plan's check lists and write sets are the ones the gate runs, lane by lane."""

    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def plan(self) -> dict:
        return plan.build(config.load(self.p.root), "T-042-09")

    def lane(self, p: dict, name: str) -> dict:
        return next(ln for ln in p["lanes"] if ln["lane"] == name)

    def assert_matches_gate(self, p: dict, lane_name: str) -> None:
        ln = self.lane(p, lane_name)
        for play, d in ln["plays"].items():
            g = Gate(config.load(self.p.root), play, "T-042-09", None)
            self.assertEqual(g.lane.name, lane_name, f"{play}: the diff should resolve to {lane_name}")
            if d is None:
                continue
            self.assertEqual(d["checks"], g.plan(), f"{lane_name} {play}")
            globs, exact = g.allowed()
            self.assertEqual((d["may_write"]["globs"], d["may_write"]["paths"]), (list(globs), sorted(exact)),
                             f"{lane_name} {play} write set")

    def test_standard_ticket_on_its_base(self) -> None:
        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        p = self.plan()
        self.assertEqual(p["declared_lane"], "standard")
        self.assertEqual([ln["lane"] for ln in p["lanes"]], ["standard", "strict"])
        self.assert_matches_gate(p, "standard")
        proof = self.lane(p, "standard")["ac_proof"]
        self.assertTrue(proof["passing_tagged_test"] and proof["red_on_base"])
        self.assertFalse(proof["passes_on_base"])
        self.assertEqual(proof["real_stack"], ["integration", "e2e"])

    def test_a_raised_lane_is_what_the_gate_runs_when_the_diff_raises_it(self) -> None:
        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        git(self.p.root, "checkout", "-q", "-b", "work")
        self.p.write("arch/CONTRACTS.md", self.p.read("arch/CONTRACTS.md") + "\n")
        self.p.commit("touch contracts")
        p = self.plan()
        self.assertEqual(p["declared_lane"], "standard", "plan reports the declared lane, not this diff's")
        self.assertIn("contract-diff", self.lane(p, "strict")["plays"]["build"]["checks"])
        self.assertNotIn("contract-diff", self.lane(p, "standard")["plays"]["build"]["checks"],
                         "each lane is planned as that lane, whatever this branch's diff resolves to")
        self.assert_matches_gate(p, "strict")

    def test_mechanical_ticket_and_its_raise_to_standard(self) -> None:
        self.p.write(PATH, ticket("mechanical", extra="transforms:\n  - rename STATES -> RETURN_STATES\n"))
        self.p.commit("ticket")
        p = self.plan()
        mech = self.lane(p, "mechanical")
        self.assertIsNone(mech["plays"]["test"], "a mechanical lane has no test play")
        self.assertFalse(mech["ac_proof"]["red_on_base"])
        self.assertEqual(mech["ac_proof"]["real_stack"], [])
        self.assert_matches_gate(p, "mechanical")
        git(self.p.root, "checkout", "-q", "-b", "work")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\nEXTRA = 1\n")
        self.p.commit("residue")
        self.assert_matches_gate(self.plan(), "standard")

    def test_refactor_ticket(self) -> None:
        self.p.write(PATH, ticket("refactor"))
        self.p.commit("ticket")
        p = self.plan()
        ref = self.lane(p, "refactor")
        self.assertIsNone(ref["plays"]["test"])
        self.assertTrue(ref["ac_proof"]["passes_on_base"])
        self.assertFalse(ref["ac_proof"]["red_on_base"])
        self.assert_matches_gate(p, "refactor")

    def test_judged_by_the_base_branch_config(self) -> None:
        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        git(self.p.root, "checkout", "-q", "-b", "work")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""'))
        self.p.commit("drop the integration command on the branch")
        p = self.plan()
        self.assertTrue(p["real_stack_suites"]["integration"], "the branch's config change does not count")
        self.assertIn("differs from main", p["config"])

    def test_spike_and_test_tickets(self) -> None:
        self.p.write(PATH, ticket().replace("type: backend", "type: spike").replace(
            '  - "AC-1: the probe answers 200"', "").replace("acceptance_criteria:", "questions:\n  - \"Q-1: does it?\"\nacceptance_criteria: []"))
        self.p.commit("spike")
        p = self.plan()
        self.assertEqual(self.lane(p, "standard")["plays"]["build"]["checks"][1:],
                         ["artifacts", "scope", "immutable", "spike", "skills"])
        self.assertIsNone(self.lane(p, "standard")["plays"]["test"])
        self.assert_matches_gate(p, "standard")
        self.p.write(PATH, ticket(areas=("tests/test_probe.py",)).replace("type: backend", "type: test"))
        self.p.commit("test ticket")
        p = self.plan()
        std = self.lane(p, "standard")
        self.assertIsNone(std["plays"]["test"], "a test ticket's build is its test play")
        self.assertIn("integration", std["plays"]["build"]["checks"])
        self.assertEqual(p["problems"], [])
        self.assert_matches_gate(p, "standard")

    def test_records_mode_pr_runs_the_build_and_test_checks(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[approval]\nmode = "forge"\nreviewers = ["rev"]\n'
                     'leads = ["lead"]\nrepo = "owner/product"\n')
        self.p.write(PATH, ticket())
        self.p.commit("records mode")
        p = self.plan()
        pr = self.lane(p, "standard")["plays"]["pr"]["checks"]
        self.assertIn("integration", pr)
        self.assertIn("ac-red", pr)
        self.assertNotIn("review-file", pr)
        self.assert_matches_gate(p, "standard")

    def test_lane_source(self) -> None:
        for edit, src in ((lambda x: x.replace("risk: low", "risk: high"), "risk: high makes it strict"),
                          (lambda x: x.replace("type: backend", "type: contract"), "type: contract makes it strict"),
                          (lambda x: x, "default: the ticket sets no lane")):
            self.p.write(PATH, edit(ticket()))
            self.p.commit("edit")
            self.assertEqual(self.plan()["lane_source"], src)
        self.p.write(PATH, ticket("strict"))
        self.p.commit("edit")
        p = self.plan()
        self.assertEqual((p["lane_source"], p["raises"], len(p["lanes"])), ("the ticket's lane field", [], 1))

    def test_read_only_and_base_option(self) -> None:
        import shutil

        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        shutil.rmtree(self.p.root / ".sdlc-run", ignore_errors=True)
        git(self.p.root, "branch", "trunk")
        p = plan.build(config.load(self.p.root), "T-042-09", "trunk")
        self.assertIn("trunk", p["config"])
        self.assertFalse((self.p.root / ".sdlc-run").exists(), "plan writes nothing")
        from unittest import mock
        with mock.patch("sdlc.gate.recover") as rec:
            plan.build(config.load(self.p.root), "T-042-09")
        rec.assert_not_called()  # it would restore files under a running ac-red

    def test_areas_widened_on_the_branch_are_noted(self) -> None:
        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        self.assertEqual(self.plan()["areas_note"], "")
        git(self.p.root, "checkout", "-q", "-b", "work")
        self.p.write(PATH, ticket(areas=("app/returns.py", "app/extra.py")))
        self.p.commit("widen")
        p = self.plan()
        self.assertIn("this branch changes the ticket's areas", p["areas_note"])
        self.assertNotIn("app/extra.py", self.lane(p, "standard")["plays"]["build"]["may_write"]["paths"])

    def test_cli_text_and_json(self) -> None:
        self.p.write(PATH, ticket())
        self.p.commit("ticket")
        code, out = self.p.sdlc("plan", "T-042-09")
        self.assertEqual(code, 0, out)
        self.assertIn("in the standard lane (declared):", out)
        self.assertIn("-> strict: the PR changes arch/CONTRACTS.md  [contracts]", out)
        self.assertIn("if raised to strict, compared with standard:", out)
        self.assertNotIn("CANNOT PASS", out)
        code, out = self.p.sdlc("plan", "T-042-09", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["acceptance_criteria"][0]["tag"], "T-042-09/AC-1")
        code, out = self.p.sdlc("plan", "T-042-99")
        self.assertNotEqual(code, 0)
        self.assertIn("no ticket T-042-99", out)


class Problems(unittest.TestCase):
    """Builds certain to fail: `plan` shows them and `lint` warns, without failing gates."""

    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def problems(self) -> list[str]:
        cfg = config.load(self.p.root)
        from sdlc.artifacts import Repo
        return plan.problems(cfg, Repo(cfg).ticket("T-042-09"))

    def test_a_listed_path_the_build_may_never_change(self) -> None:
        self.p.write(PATH, ticket(areas=("app/returns.py", "sdlc.toml", "tests/test_probe.py")))
        probs = self.problems()
        self.assertEqual(len(probs), 2, probs)
        self.assertIn("lists sdlc.toml, but the build may never change it: a lead artifact", probs[0])
        self.assertIn("lists tests/test_probe.py, but the build may never change it: the test play's file", probs[1])

    def test_globs_contracts_and_area_files_are_not_problems(self) -> None:
        self.p.write(PATH, ticket(areas=("app/**", "arch/CONTRACTS.md", "app/returns.py")))
        self.assertEqual(self.problems(), [])

    def test_owing_real_stack_proof_with_no_suite_command(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""'))
        self.p.write(PATH, ticket())
        self.assertEqual(len(self.problems()), 1)
        self.assertIn("owes real-stack proof", self.problems()[0])
        self.p.write(PATH, ticket(extra="test: none\n"))
        self.assertEqual(self.problems(), [], "test: none owes no real-stack proof")
        self.p.write(PATH, ticket("refactor"))
        self.assertEqual(self.problems(), [], "a refactor ticket has no test play to prove it")

    def test_refactor_lane_without_a_junit_unit_command(self) -> None:
        self.p.write(PATH, ticket("refactor"))
        self.assertEqual(self.problems(), [])
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'unit = "python tools/junit.py --start app --out {junit}"', 'unit = "python tools/junit.py --start app"'))
        probs = self.problems()
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("refactor lane, which needs a unit command with {junit}", probs[0])

    def test_what_scope_lets_the_build_change_is_not_a_problem(self) -> None:
        self.p.write(PATH, ticket(areas=("app/returns.py", "sdlc-baseline.json", "evidence/T-042-09.build.json",
                                         PATH)))
        self.assertEqual(self.problems(), [])
        self.p.write(PATH, ticket(areas=("app/returns.py", "evidence/T-042-09.test.json")))
        self.assertEqual(len(self.problems()), 1, "the test play's evidence is not the build's")

    def test_a_test_ticket_listing_a_non_test_path(self) -> None:
        self.p.write(PATH, ticket(areas=("tests/test_probe.py",)).replace("type: backend", "type: test"))
        self.assertEqual(self.problems(), [])
        self.p.write(PATH, ticket(areas=("tests/test_probe.py", "app/returns.py", "arch/CONTRACTS.md"))
                     .replace("type: backend", "type: test"))
        probs = self.problems()
        self.assertEqual(len(probs), 2, probs)
        self.assertIn("lists app/returns.py, but a test ticket changes tests only", probs[0])
        self.assertIn("lists arch/CONTRACTS.md, but a test ticket changes tests only", probs[1])

    def test_real_stack_rule_needs_ac_coverage_in_the_proving_play(self) -> None:
        cfg = self.p.read("sdlc.toml").replace(
            'integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""')
        self.p.write("sdlc.toml", cfg)
        self.p.write(PATH, ticket())
        self.assertEqual(len(self.problems()), 1)
        self.p.write("sdlc.toml", cfg + '\n[gate]\ntest = ["artifacts", "scope", "unit"]\n')
        self.assertEqual(self.problems(), [], "without ac-coverage in the test play nothing demands the tag")
        self.p.write("sdlc.toml", cfg + '\n[gate]\ntest = ["artifacts", "scope", "unit"]\n'
                     '\n[approval]\nmode = "forge"\nreviewers = ["rev"]\nleads = ["lead"]\nrepo = "owner/product"\n')
        self.assertEqual(len(self.problems()), 1, "in records mode the PR runs the build list's ac-coverage too")
        self.p.write("sdlc.toml", cfg + '\n[gate]\ntest = ["artifacts", "scope", "unit"]\n')
        self.p.write(PATH, ticket(areas=("tests/test_probe.py",)).replace("type: backend", "type: test"))
        self.assertEqual(len(self.problems()), 1, "a test ticket's build is the play that proves it")

    def test_lint_warns_and_gates_do_not_fail_on_it(self) -> None:
        self.p.write(PATH, ticket(areas=("app/returns.py", "sdlc.toml")))
        code, out = self.p.sdlc("lint")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  tickets/T-042-09-plan-probe.md: cannot pass as written: lists sdlc.toml", out)
        self.assertIn("(sdlc plan T-042-09)", out)
        code, out = self.p.sdlc("lint", "--strict")
        self.assertNotEqual(code, 0, "--strict fails on it")
        code, out = self.p.sdlc("plan", "T-042-09")
        self.assertIn("CANNOT PASS as written:\n  - lists sdlc.toml", out)

    def test_a_shipped_ticket_is_not_judged(self) -> None:
        self.p.write(PATH, ticket(areas=("app/returns.py", "sdlc.toml")).replace("status: ready", "status: done"))
        code, out = self.p.sdlc("lint")
        self.assertNotIn("cannot pass", out)


if __name__ == "__main__":
    unittest.main()
