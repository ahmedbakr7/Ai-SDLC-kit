"""ADR-0007: a ticket's test_files widens the test play's write set, as the base branch has it.
Each rule has a test that catches the defect it exists for and one that shows the reference
passes."""
import json
import unittest

from helpers import ProductRepo, git
from sdlc import config, lint, prompt
from sdlc.approval import Record, _content_problems
from sdlc.artifacts import Repo
from sdlc.gate import Gate, _glob, _review_entries

TID = "T-042-02"
PATH = "tickets/T-042-02-order-page.md"


class TestFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()
        self.original = self.p.read(PATH)

    def tearDown(self) -> None:
        self.p.close()

    def set_test_files(self, *entries: str, extra: str = "") -> None:
        text = self.original
        lines = "".join(f"  - {e}\n" for e in entries)
        self.p.write(PATH, text.replace("shared: []\n", f"shared: []\n{extra}test_files:\n{lines}", 1))

    def branch(self) -> str:
        git(self.p.root, "checkout", "-q", "-b", f"build/{TID}")
        return git(self.p.root, "rev-parse", "HEAD").strip()

    def scope(self, play: str, start: str) -> dict:
        self.p.sdlc("gate", play, TID, "--since", start, "--only", "scope")
        return json.loads(self.p.read(f".sdlc-run/{TID}.{play}.json"))["checks"][0]

    def gate(self, play: str = "build") -> Gate:
        return Gate(config.load(self.p.root), play, TID, None)

    # -- write sets -------------------------------------------------------
    def test_the_test_play_may_write_its_test_files(self) -> None:
        self.set_test_files("support/seed.py", "fixtures/**")
        self.p.commit("lead: test_files")
        start = self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.write("fixtures/orders.json", "{}\n")
        self.p.commit("test support")
        c = self.scope("test", start)
        self.assertEqual(c["status"], "pass", c)

    def test_without_test_files_the_same_files_are_outside_the_test_play(self) -> None:
        start = self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.commit("test support")
        c = self.scope("test", start)
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside test write set: support/seed.py", c["details"])

    def test_a_branch_cannot_widen_its_own_test_files(self) -> None:
        start = self.branch()
        self.set_test_files("support/seed.py")
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.commit("widen on the branch")
        self.assertEqual(self.gate("test").test_files(), [])
        c = self.scope("test", start)
        self.assertIn("outside test write set: support/seed.py", c["details"])

    def test_test_files_never_cover_production_source(self) -> None:
        self.set_test_files("app/pages.py")
        self.p.commit("lead: a bad test_files entry")
        start = self.branch()
        self.p.write("app/pages.py", "# changed by the test play\n")
        self.p.commit("test play edits production")
        c = self.scope("test", start)
        self.assertEqual(c["status"], "fail")
        self.assertIn("test_files may not cover production source (tests.source_globs, else the ticket's "
                      "areas and shared): app/pages.py", c["details"])

    def test_the_build_may_never_write_the_test_files(self) -> None:
        self.set_test_files("support/seed.py")
        self.p.commit("lead: test_files")
        start = self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.commit("build writes the test play's file")
        c = self.scope("build", start)
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("why support/seed.py is out of bounds: the test play's file (the ticket's test_files)",
                      c["details"])

    def test_without_test_files_the_build_may_write_it_as_a_flag(self) -> None:
        start = self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.commit("build writes a helper")
        c = self.scope("build", start)
        self.assertEqual(c["status"], "pass", c)

    # -- test code, not production ------------------------------------------
    def test_a_test_files_entry_is_not_production_for_the_base_run(self) -> None:
        self.set_test_files("support/**")
        self.p.commit("lead: test_files")
        self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.write("app/pages.py", "# build change\n")
        self.p.commit("work")
        prod = self.gate()._production_changes(every=True)
        self.assertIn("app/pages.py", prod)
        self.assertNotIn("support/seed.py", prod)

    # -- the review names each one ------------------------------------------
    def test_changes_the_review_must_name(self) -> None:
        self.set_test_files("support/**", "tests/fixtures/**")
        self.p.commit("lead: test_files")
        self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.write("tests/fixtures/orders.json", "{}\n")  # tests/** already the test play's
        self.p.commit("test support")
        self.assertEqual(self.gate().test_file_changes(), ["support/seed.py"])

    def test_an_approval_names_each_test_files_change(self) -> None:
        t = Repo(config.load(self.p.root)).ticket(TID)
        rows = "".join(f"| AC-{i} | x | y |\n" for i in (1, 2, 3))

        def problems(body: str) -> list[str]:
            rec = Record(sha="0" * 40, who="r", role="review", verdict="approve", body=rows + body)
            return _content_problems(rec, "review", t, "standard", [], [], _review_entries, _glob,
                                     test_changes=["support/seed.py"])

        self.assertEqual(problems(""), ["test_files file not named under ## Test files: support/seed.py"])
        self.assertEqual(problems("\n## Test files\n\n- `support/seed.py` seeds two orders\n"), [])
        self.assertEqual(len(problems("\n## Test files\n\n- `**` everything\n")), 1, "a bare glob names nothing")

    def test_the_review_file_names_each_test_files_change(self) -> None:
        self.set_test_files("support/**")
        self.p.commit("lead: test_files")
        self.branch()
        self.p.write("support/seed.py", "SEED = 1\n")
        self.p.commit("test support")
        rows = "".join(f"| AC-{i} | x | y |\n" for i in (1, 2, 3))
        head = git(self.p.root, "rev-parse", "HEAD").strip()

        def details(extra: str) -> list[str]:
            self.p.write(f"reviews/{TID}.md", f"---\nticket: {TID}\nverdict: approve\ncommit: {head}\n---\n\n"
                         f"## Gate\n\npass\n\n## Acceptance criteria\n\n| AC | Proof | What |\n|---|---|---|\n{rows}"
                         f"\n## Findings\n\nNone.\n{extra}")
            self.p.sdlc("gate", "review", TID, "--only", "review-file")
            return json.loads(self.p.read(f".sdlc-run/{TID}.review.json"))["checks"][0]["details"]

        missing = f"a test_files file not named under ## Test files in reviews/{TID}.md: support/seed.py"
        self.assertIn(missing, details(""))
        self.assertNotIn(missing, details("\n## Test files\n\n- `support/seed.py` seeds two orders\n"))

    # -- lint ---------------------------------------------------------------
    def lint(self) -> list[str]:
        repo = Repo(config.load(self.p.root))
        return [i.msg for i in lint.lint_repo(repo, only_ticket=TID) if i.level == "error"]

    def test_lint_accepts_test_support_files(self) -> None:
        self.set_test_files("support/seed.py", "fixtures/**")
        self.assertEqual(self.lint(), [])

    def test_lint_refuses_a_non_list(self) -> None:
        text = self.p.read(PATH)
        self.p.write(PATH, text.replace("shared: []\n", "shared: []\ntest_files: support/seed.py\n", 1))
        self.assertIn("test_files must be a list of paths or globs", self.lint())

    def test_lint_refuses_production_source(self) -> None:
        self.set_test_files("app/pages.py")
        self.assertTrue(any("test_files entry app/pages.py covers production source app/pages.py" in m
                            for m in self.lint()), self.lint())
        self.set_test_files("app/*.py")
        self.assertTrue(any("test_files entry app/*.py covers production source" in m for m in self.lint()),
                        self.lint())

    def test_lint_refuses_the_tickets_own_areas_even_with_source_globs(self) -> None:
        # The build may never write a test_files file, so one in its areas could never pass.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'integration_globs = ["tests/**"]', 'integration_globs = ["tests/**"]\nsource_globs = ["lib/**"]', 1))
        self.set_test_files("app/server.py")
        self.assertTrue(any("test_files entry app/server.py covers production source app/server.py" in m
                            for m in self.lint()), self.lint())
        self.set_test_files("support/seed.py")
        self.assertEqual(self.lint(), [])

    def test_plan_shows_the_wider_test_write_set(self) -> None:
        from sdlc import plan
        self.set_test_files("support/seed.py")
        self.p.commit("lead: test_files")
        p = plan.build(config.load(self.p.root), TID)
        play = p["lanes"][0]["plays"]["test"]
        self.assertIn("support/seed.py", play["may_write"]["globs"])
        self.assertNotIn("support/seed.py", p["lanes"][0]["plays"]["build"]["may_write"]["globs"])

    def test_lint_refuses_what_no_play_may_write(self) -> None:
        self.set_test_files("sdlc.toml")
        self.assertTrue(any("test_files entry sdlc.toml covers a file no play may write: a lead artifact" in m
                            for m in self.lint()), self.lint())

    def test_lint_refuses_test_files_on_a_ticket_with_no_test_play(self) -> None:
        self.set_test_files("support/seed.py", extra="test: none\n")
        self.assertIn("test_files has no effect: the ticket has no test play (marked test: none)", self.lint())
        self.set_test_files("support/seed.py", extra="lane: refactor\n")
        self.assertIn("test_files has no effect: the refactor lane has no test play", self.lint())

    # -- prompt -------------------------------------------------------------
    def test_the_test_prompt_lists_the_test_files(self) -> None:
        self.set_test_files("support/seed.py")
        cfg = config.load(self.p.root)
        t = Repo(cfg).ticket(TID)
        self.assertIn("- `support/seed.py` (the ticket's test_files", prompt._write_set(cfg, t, "test"))
        self.assertNotIn("support/seed.py", prompt._write_set(cfg, t, "build"))


if __name__ == "__main__":
    unittest.main()
