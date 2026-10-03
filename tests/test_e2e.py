"""End to end: drive a (fake) agent through build -> review -> merge with the gate in the loop."""
import json
import os
import unittest

from helpers import ProductRepo, git


class Conveyor(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        os.environ.pop("FAKE_AGENT_STRAY", None)
        self.p.close()

    def test_build_retries_on_gate_failure_then_review_then_merge(self) -> None:
        p = self.p
        self.assertEqual(p.sdlc("next")[1].strip(), "T-042-02")

        os.environ["FAKE_AGENT_STRAY"] = "1"
        code, out = p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertEqual(code, 0, out)
        self.assertIn("attempt 2/3", out)                       # first attempt was rejected
        self.assertIn("outside build write set: app/stray_helper.py", out)  # ... by the scope check
        self.assertFalse((p.root / "app" / "stray_helper.py").exists())
        self.assertEqual(p.sdlc("status", "T-042-02")[1].strip(), "in_review")
        ev = json.loads(p.read("evidence/T-042-02.build.json"))
        self.assertEqual(ev["result"], "pass")
        self.assertFalse(ev["dirty"])
        self.assertEqual({v["status"] for v in ev["ac"].values()}, {"passed"})
        smoke = next(c for c in ev["checks"] if c["name"] == "smoke")
        self.assertIn("2 route/page probe(s)", smoke["summary"])

        # Plays start from wherever the operator is; the runner reads the ticket's branch.
        git(p.root, "checkout", "-q", "main")
        code, out = p.sdlc("run", "test", "T-042-02", "--agent", "fake")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(p.read("evidence/T-042-02.test.json"))["result"], "pass")

        code, out = p.sdlc("run", "review", "T-042-02", "--agent", "fake")
        self.assertNotEqual(code, 0)
        self.assertIn("review it with a different agent", out)

        code, out = p.sdlc("run", "review", "T-042-02", "--agent", "fake-reviewer")
        self.assertEqual(code, 0, out)
        self.assertNotIn("attempt 2", out)
        self.assertIn("verdict: approve", p.read("reviews/T-042-02.md"))

        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertEqual(code, 0, out)
        p.commit("merge: T-042-02 done")
        log = git(p.root, "log", "--format=%s%n%b")
        self.assertIn("Sdlc-Agent: fake\nSdlc-Play: build", log)
        self.assertIn("Sdlc-Agent: fake-reviewer\nSdlc-Play: review", log)
        # What product CI runs on this PR: the whole branch is in the ticket's write sets.
        code, out = p.sdlc("gate", "pr", "--base", "main")
        self.assertEqual(code, 0, out)
        self.assertIn("gate pr: ticket T-042-02", out)

    def test_approval_does_not_cover_code_changed_after_review(self) -> None:
        p = self.p
        self.assertEqual(p.sdlc("run", "build", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "test", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "review", "T-042-02", "--agent", "fake-reviewer")[0], 0)
        p.write("app/pages.py", p.read("app/pages.py") + "\n# after the review\n")
        p.commit("late change")
        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertNotEqual(code, 0)
        self.assertIn("changed after the reviewed commit", out)
        p.write("tickets/T-042-02-order-page.md",
                p.read("tickets/T-042-02-order-page.md").replace("status: in_review", "status: done"))
        p.commit("hand-set done")
        code, out = p.sdlc("gate", "pr", "T-042-02", "--base", "main")
        self.assertNotEqual(code, 0)
        self.assertIn("changed after the reviewed commit", out)
        self.assertIn("app/pages.py", out)

    def test_approval_ignores_what_does_not_merge(self) -> None:
        # Hangout #59: CI's `npm install` left an untracked package-lock.json, and the PR gate
        # called the approved ticket "changed after the reviewed commit". Files that came in
        # from main after the review are not this PR's change either.
        p = self.p
        # Lockfiles are always in scope, as in the node profiles; the approval check is the subject.
        p.write("sdlc.toml", p.read("sdlc.toml") + '\n[scope]\nalways_allowed = ["package-lock.json"]\n')
        p.commit("lead: lockfiles in scope")
        self.assertEqual(p.sdlc("run", "build", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "test", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "review", "T-042-02", "--agent", "fake-reviewer")[0], 0)
        branch = git(p.root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        git(p.root, "checkout", "-q", "main")
        p.write("docs/elsewhere.md", "a lead change on main after the review\n")
        p.commit("main moves on")
        git(p.root, "checkout", "-q", branch)
        git(p.root, "merge", "-q", "--no-edit", "main")
        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertEqual(code, 0, out)
        p.commit("merge: T-042-02 done")
        p.write("package-lock.json", "{}\n")  # untracked, as `npm install` leaves it in CI
        code, out = p.sdlc("gate", "pr", "T-042-02", "--base", "main")
        self.assertEqual(code, 0, out)
        self.assertNotIn("changed after the reviewed commit", out)

    def test_a_look_alike_of_the_review_file_is_a_change(self) -> None:
        # CodeRabbit on kit #8: paths were whitespace-stripped, so "reviews/T-042-02.md "
        # passed as the review file both scope and the approval check allow after review.
        p = self.p
        self.assertEqual(p.sdlc("run", "build", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "test", "T-042-02", "--agent", "fake")[0], 0)
        self.assertEqual(p.sdlc("run", "review", "T-042-02", "--agent", "fake-reviewer")[0], 0)
        p.write("reviews/T-042-02.md ", "not reviewed\n")
        p.commit("a file named like the review")
        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertNotEqual(code, 0, out)
        self.assertIn("changed after the reviewed commit", out)
        self.assertIn("reviews/T-042-02.md ", out)

    def test_an_agent_with_build_or_test_commits_cannot_review(self) -> None:
        p = self.p
        self.assertEqual(p.sdlc("run", "build", "T-042-02", "--agent", "fake")[0], 0)
        # Another agent adds a commit in a later play: the builder is still an author.
        p.write("tests/test_extra.py", '"""integration tests"""\n')
        git(p.root, "add", "-A")
        git(p.root, "commit", "-q", "-m", "test T-042-02", "-m", "Sdlc-Agent: fake-reviewer\nSdlc-Play: test")
        for agent in ("fake", "fake-reviewer"):
            with self.subTest(agent=agent):
                code, out = p.sdlc("run", "review", "T-042-02", "--agent", agent)
                self.assertNotEqual(code, 0)
                self.assertIn(f"has build/test commits by {agent}", out)

    def test_test_play_must_add_real_stack_proof(self) -> None:
        # Unit tests from the build already carry every tag; a test play that adds nothing
        # must not pass.
        p = self.p
        self.assertEqual(p.sdlc("run", "build", "T-042-02", "--agent", "fake")[0], 0)
        code, out = p.sdlc("gate", "test", "T-042-02")
        self.assertNotEqual(code, 0)
        self.assertIn("no passing integration/e2e test carries a T-042-02/AC-n tag", out)

    def test_build_refuses_a_dirty_tree(self) -> None:
        self.p.write("notes.txt", "uncommitted")
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertNotEqual(code, 0)
        self.assertIn("dirty", out)

    def test_run_recovers_files_an_interrupted_ac_red_reverted(self) -> None:
        # ac-red was killed after reverting production files: the tree is dirty and the
        # backup holds the only copy. The next run restores them instead of refusing to start.
        p = self.p
        backup = p.root / ".sdlc-run" / "red-backup"
        backup.mkdir(parents=True)
        original = (p.root / "app" / "returns.py").read_bytes()
        (backup / "0").write_bytes(original)
        (backup / "manifest.json").write_text(json.dumps({"app/returns.py": "0", "app/new.py": None}),
                                              encoding="utf-8")
        p.write("app/returns.py", "# reverted by ac-red\n")
        p.write("app/new.py", "# not in the working tree before ac-red; it wrote the base version\n")
        code, out = p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("restored 2 file(s)", out)
        self.assertEqual((p.root / "app" / "returns.py").read_bytes(), original)
        self.assertFalse((p.root / "app" / "new.py").exists())
        self.assertFalse(backup.exists())

    def test_build_refuses_unmet_dependencies(self) -> None:
        p = self.p
        t1 = p.read("tickets/T-042-01-returns-api.md").replace("status: done", "status: in_review")
        p.write("tickets/T-042-01-returns-api.md", t1)
        p.commit("T-042-01 back in review")
        code, out = p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertNotEqual(code, 0)
        self.assertIn("depends_on not done", out)

    def test_review_without_approve_cannot_merge(self) -> None:
        p = self.p
        self.assertEqual(p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)
        p.commit("start")
        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertNotEqual(code, 0)
        self.assertIn("not a legal move", out)


if __name__ == "__main__":
    unittest.main()
