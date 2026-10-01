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

        code, out = p.sdlc("run", "review", "T-042-02", "--agent", "fake")
        self.assertNotEqual(code, 0)
        self.assertIn("different agent", out)

        code, out = p.sdlc("run", "review", "T-042-02", "--agent", "fake-reviewer")
        self.assertEqual(code, 0, out)
        self.assertNotIn("attempt 2", out)
        self.assertIn("verdict: approve", p.read("reviews/T-042-02.md"))

        code, out = p.sdlc("status", "T-042-02", "done", "--as", "merge")
        self.assertEqual(code, 0, out)
        log = git(p.root, "log", "--format=%s%n%b")
        self.assertIn("Sdlc-Agent: fake", log)
        self.assertIn("Sdlc-Agent: fake-reviewer", log)

    def test_build_refuses_a_dirty_tree(self) -> None:
        self.p.write("notes.txt", "uncommitted")
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertNotEqual(code, 0)
        self.assertIn("dirty", out)

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
