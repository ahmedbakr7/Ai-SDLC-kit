"""End to end over ADR-0001 step 2 and ADR-0002: one product's main branch taken through a
ticket, known debt, a file move, a waiver and the fix, with the full gates, approvals and
derived status its CI runs at each step. The per-check tests prove each rule on its own; this
proves they hold together on one history. The forge is faked: CI never touches the network."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

from helpers import ProductRepo, git
import test_gate  # the module, not its TestCase classes: importing those would run them here too
from test_approval import RECORDS, REVIEW_BODY, FakeGitHub, commit, copy_solution

from sdlc import approval, config

TICKET = "T-042-02"
KEY = "app/legacy.py: TS2345"
HOTFIX_KEY = "app/hotfix.py: TS2345"
NOT_IN_THIS_PRODUCT = ("e2e", "duplication")  # the example has no e2e suite and no duplication tool


class Lifecycle(unittest.TestCase):
    extra = ""

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write("tools/fake_tsc.py", test_gate.BaselineRenames.TSC)  # reports `file(line,col): error TS2345`
        cfg = self.p.read("sdlc.toml").replace(
            'typecheck = "python tools/lint.py --types"',
            f"typecheck = '\"{Path(sys.executable).as_posix()}\" tools/fake_tsc.py'")
        self.p.write("sdlc.toml", cfg + RECORDS + self.extra)
        self.p.commit("lead: approvals outside the tree; a typechecker that names files")
        self._client = approval.forge_client
        self.fake: FakeGitHub | None = None
        self.prs = 0
        approval.forge_client = lambda cfg: self.fake

    def tearDown(self) -> None:
        approval.forge_client = self._client
        self.p.close()

    # -- what a product's CI and its people do ---------------------------------------------

    def head(self) -> str:
        return git(self.p.root, "rev-parse", "HEAD").strip()

    def branch(self, name: str) -> None:
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "checkout", "-q", "-b", name)

    def open_pr(self, author: str) -> None:
        self.prs += 1
        self.fake = FakeGitHub(self.prs, author, self.head())

    def record(self, who: str, role: str = "review", agent: str = "reviewer", ticket: str = TICKET,
               body: str = REVIEW_BODY) -> None:
        self.fake.comments.append({"user": {"login": who}, "author_association": "COLLABORATOR",
                                   "created_at": "2026-10-06T10:00:00Z",
                                   "body": approval.render(ticket, self.head(), "approve", role, agent, body)})

    def approval(self) -> tuple[int, str]:
        code, out = self.p.sdlc("approval", "--pr", str(self.prs), "--base", "main")
        res = json.loads((self.p.root / ".sdlc-run" / "approval.json").read_text(encoding="utf-8"))
        return code, res["summary"]

    def merge(self, branch: str) -> None:
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{self.prs}", branch)

    def gate_ci(self, *extra: str) -> tuple[int, str]:
        return self.p.sdlc("gate", "ci", *extra)

    def assert_passes(self, result: tuple[int, str]) -> str:
        code, out = result
        self.assertEqual(code, 0, out)
        return out

    def assert_fails(self, result: tuple[int, str]) -> str:
        code, out = result
        self.assertNotEqual(code, 0, out)
        return out

    def lead_pr(self, branch: str, author: str = "ahmed") -> None:
        """A PR without a ticket: the full PR gate passes, and only a lead's record approves it."""
        self.assert_passes(self.p.sdlc("gate", "pr", "--base", "main"))
        self.open_pr(author)
        code, summary = self.approval()
        self.assertNotEqual(code, 0, summary)
        self.assertIn("needs a lead approval", summary)
        self.record("lead", role="lead", agent="", ticket="", body="Signed off.")
        self.assert_passes(self.approval())
        self.merge(branch)

    def ship_the_ticket(self) -> None:
        """Build and test plays by two agents, the PR gate on the head, an independent review."""
        self.assertEqual(self.p.sdlc("next")[1].strip(), TICKET)
        self.branch(f"build/{TICKET}")
        copy_solution(self.p, f"build-{TICKET}")
        commit(self.p, f"{TICKET}: order page returns section", agent="builder", play="build")
        copy_solution(self.p, f"test-{TICKET}")
        commit(self.p, f"{TICKET}: real-stack tests", agent="tester", play="test")
        self.assertIn(f"gate pr: ticket {TICKET}", self.assert_passes(self.p.sdlc("gate", "pr", "--base", "main")))

        self.open_pr("builder-bot")
        code, summary = self.approval()
        self.assertNotEqual(code, 0, summary)                   # no review yet
        self.record("rev", agent="builder")
        self.assertNotEqual(self.approval()[0], 0)              # the building agent cannot review
        self.record("rev")
        self.assert_passes(self.approval())

        self.merge(f"build/{TICKET}")
        self.assertEqual(self.p.sdlc("status", TICKET)[1].strip(), "done")  # derived from the merge
        self.assertNotIn(TICKET, self.p.sdlc("next")[1])
        self.assert_passes(self.gate_ci())

    # -- the stories -------------------------------------------------------------------------

    def test_a_ticket_goes_from_ready_to_done_through_every_gate(self) -> None:
        self.assert_passes(self.gate_ci())
        self.assertEqual(self.p.sdlc("status", TICKET)[1].strip(), "ready")
        self.ship_the_ticket()
        self.assertIn(f"{TICKET}: done", self.assert_passes(self.p.sdlc("trace")))

    def test_debt_is_baselined_moved_waived_and_paid_off(self) -> None:
        p = self.p
        today = dt.date.today()

        # Main goes red with debt the lead cannot fix today: it is baselined, counted per key.
        p.write("app/legacy.py", "A = 1  # TYPEERR\nB = 2  # TYPEERR\n")
        p.commit("main is red: two type errors in one file")
        self.assertIn("app/legacy.py(1,1): error TS2345", self.assert_fails(self.gate_ci()))
        self.assert_passes(p.sdlc("baseline"))
        self.assertEqual(json.loads(p.read("sdlc-baseline.json")),
                         {"version": 2, "checks": {"typecheck": {KEY: 2}}})
        p.commit("lead: baseline")
        self.assertIn("BASELINED: 2 known failure(s)", self.assert_passes(self.gate_ci()))

        # A ticket ships on top of the debt.
        self.ship_the_ticket()

        # Moving the file keeps its known failures known, on the branch and on main after.
        self.branch("lead/move")
        git(p.root, "mv", "app/legacy.py", "app/old_legacy.py")
        p.commit("move legacy")
        self.assertIn("BASELINED: 2 known failure(s)", self.assert_passes(self.gate_ci("--base", "main")))
        self.lead_pr("lead/move")
        self.assertIn("BASELINED: 2 known failure(s)", self.assert_passes(self.gate_ci()))

        # A hotfix lands red. A branch cannot waive it; the lead's waiver applies once on main.
        p.write("app/hotfix.py", "C = 3  # TYPEERR\n")
        p.commit("hotfix: pushed by the lead with a type error")
        self.assertIn("1 new failure(s) not in sdlc-baseline.json", self.assert_fails(self.gate_ci()))
        self.branch("lead/waive")
        expires = today + dt.timedelta(days=30)
        p.write("sdlc-waivers.toml",
                f'[[waiver]]\nid = "W-1"\ncheck = "typecheck"\nkey = "{HOTFIX_KEY}"\ncount = 1\n'
                f'owner = "lead"\nreason = "vendor types land next sprint"\nexpires = {expires.isoformat()}\n')
        p.commit("lead: waive the hotfix type error")
        self.assertIn("pending: W-1 applies once it is on main", self.assert_fails(self.gate_ci("--base", "main")))
        self.lead_pr("lead/waive")                              # merged by admin override: main is red
        out = self.assert_passes(self.gate_ci())
        self.assertIn(f"waived: {HOTFIX_KEY}: W-1 (owner lead, expires {expires.isoformat()})", out)
        self.assertIn("BASELINED: 2 known failure(s)", out)

        # The fix leaves a stale baseline and a stale waiver: CI holds it until both are removed.
        self.branch("fix/types")
        p.write("app/old_legacy.py", "A = 1\nB = 2\n")
        p.write("app/hotfix.py", "C = 3\n")
        p.commit("fix the type errors")
        out = self.assert_fails(self.gate_ci("--base", "main"))
        self.assertIn("stale waiver: W-1", out)
        self.assertIn("sdlc baseline --prune", out)
        self.assert_passes(p.sdlc("baseline", "--prune"))
        (p.root / "sdlc-waivers.toml").unlink()
        p.commit("lead: prune the baseline and drop the waiver")
        self.assert_passes(self.gate_ci("--base", "main"))
        self.lead_pr("fix/types")
        out = self.assert_passes(self.gate_ci())
        self.assertNotIn("BASELINED", out)
        self.assertNotIn("waived", out.lower())  # the summary (WAIVED) and the per-key lines (waived:)
        self.assertEqual(json.loads(p.read("sdlc-baseline.json"))["checks"].get("typecheck", {}), {})


class HardenedLifecycle(Lifecycle):
    """The same stories with main on `[gate] preset = "hardened"`. Nothing is optional there, so
    this product, which has no e2e suite and no duplication tool, says so in its own lists and
    proves tickets over integration tests; doctor finds nothing the preset forbids."""

    extra = '\n[gate]\npreset = "hardened"\n' + "".join(
        f"{k} = {json.dumps([c for c in config.DEFAULTS['gate'][k] if c not in NOT_IN_THIS_PRODUCT])}\n"
        for k in ("build", "test", "ci", "mechanical"))

    def setUp(self) -> None:
        super().setUp()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[tests]\n", '[tests]\nreal_stack = ["integration"]\n', 1))
        self.p.commit("lead: integration is this product's real stack")
        out = self.assert_passes(self.p.sdlc("doctor"))
        self.assertIn("preset: hardened", out)
        self.assertIn("gate.optional: (empty)", out)
        self.assertNotIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
