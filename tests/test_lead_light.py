"""ADR-0008: a lead PR that changes only prose in [scope] lead_light needs one approving review
from any reviewer or bot. Each rule has a test that catches the defect it exists for and one
that shows the reference passes."""
import unittest

from helpers import git
from test_approval import Base

from sdlc import adapters, approval, config
from sdlc.gate import light_overlaps, light_protected

LIGHT = '\n[scope]\nlead_light = ["README.md", "docs/**"]\n'


class LightPath(Base):
    extra = LIGHT

    def lead_pr(self, files: dict[str, str]) -> str:
        git(self.p.root, "checkout", "-q", "-b", "lead/docs")
        for rel, text in files.items():
            self.p.write(rel, text)
        self.p.commit("lead: prose")
        self.forge()
        return git(self.p.root, "rev-parse", "HEAD").strip()

    def test_one_approval_from_any_reviewer_takes_a_prose_only_pr(self) -> None:
        head = self.lead_pr({"README.md": "# Returns\n\nTypo fixed.\n", "docs/guide.md": "# Guide\n"})
        code, _, res = self.approval()
        self.assertNotEqual(code, 0, "never zero approvals")
        self.assertIn("this PR (lead PR, light: prose only ([scope] lead_light)) needs an approving review "
                      "(any reviewer or bot)", res["summary"])
        self.record("rev", head, agent="", body="ok", ticket="")
        code, _, res = self.approval()
        self.assertEqual(code, 0, res)
        self.assertIn("(lead PR, light: prose only ([scope] lead_light)) approved", res["summary"])

    def test_a_bot_approval_takes_it_too(self) -> None:
        head = self.lead_pr({"README.md": "# Returns\n"})
        self.record("bot", head, role="bot", agent="", body="ok", ticket="")
        self.assertEqual(self.approval()[0], 0)

    def test_one_file_outside_lead_light_needs_both_approvals(self) -> None:
        head = self.lead_pr({"README.md": "# Returns\n", "notes.txt": "x\n"})
        self.record("rev", head, agent="", body="ok", ticket="")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("this PR (lead PR) needs a lead approval", res["summary"])

    def test_a_broad_glob_never_lightens_a_protected_path(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'lead_light = ["README.md", "docs/**"]', 'lead_light = ["**"]'))
        self.p.commit("lead: a careless glob")
        rel = "tickets/T-042-02-order-page.md"
        head = self.lead_pr({"README.md": "# Returns\n", rel: self.p.read(rel) + "\nA lead note.\n"})
        self.record("rev", head, agent="", body="ok", ticket="")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("this PR (lead PR) needs a lead approval", res["summary"])
        code, out = self.p.sdlc("doctor")
        self.assertIn("[scope] lead_light glob ** covers", out)

    def test_without_lead_light_a_readme_pr_needs_both(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(LIGHT, "\n"))
        self.p.commit("lead: no light path")
        head = self.lead_pr({"README.md": "# Returns\n"})
        self.record("rev", head, agent="", body="ok", ticket="")
        self.assertNotEqual(self.approval()[0], 0)

    def test_the_hardened_preset_forbids_it(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[approval]", '[gate]\npreset = "hardened"\n\n[approval]', 1))
        self.p.commit("lead: hardened")
        cfg = config.load(self.p.root)
        self.assertEqual(cfg.section("scope")["lead_light"], [])
        self.assertTrue(any("[scope] lead_light is forbidden by the hardened preset" in p for p in cfg.preset_problems))
        cfg.data["scope"]["lead_light"] = ["README.md"]  # even if it got through
        self.assertFalse(approval.light(cfg, ["README.md"]))

    def test_doctor_lists_the_globs_and_refuses_a_non_list(self) -> None:
        code, out = self.p.sdlc("doctor")
        self.assertIn("note  [scope] lead_light (one approval from any reviewer or bot", out)
        self.assertNotIn("[scope] lead_light glob", out)
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'lead_light = ["README.md", "docs/**"]', 'lead_light = "README.md"'))
        self.assertIn("[scope] lead_light must be a list of globs", self.p.sdlc("doctor")[1])


class Protected(Base):
    """The protected list covers each kind of path the kit reads as instructions or data."""
    extra = LIGHT

    def test_each_path_kind_is_protected(self) -> None:
        cfg = config.load(self.p.root)
        kinds = ["AGENTS.md", *adapters.files(cfg), "skills/backend-patterns/SKILL.md", ".sdlc/AGENTS.md", ".sdlc",
                 "tickets/T-042-02-order-page.md", "intent/intent-042.md", "design/spec-042.md", "arch/plan-042.md",
                 "arch/CONTRACTS.md", "decisions/ADR-0001-stack.md", "ops/runbook.md", "sdlc.toml",
                 "sdlc-baseline.json", "sdlc-waivers.toml", "skills.lock.json", ".github/workflows/sdlc.yml",
                 ".claude/settings.json", ".github/CODEOWNERS",
                 "tests/test_api.py", "app/test_returns.py"]
        prot = light_protected(cfg)
        from sdlc.gate import _glob
        for f in kinds:
            with self.subTest(f=f):
                self.assertTrue(any(f == g or _glob(f, g) for g in prot), f)
                self.assertFalse(approval.light(cfg, [f]))
        self.assertTrue(approval.light(cfg, ["README.md", "docs/guide.md"]))

    def test_overlaps_judge_the_glob_itself(self) -> None:
        cfg = config.load(self.p.root)
        for g in ("**/*.md", "*.md", "AGENTS.md", "tickets/**", "**", "intent/*", "tickets/*.md"):
            with self.subTest(g=g):
                self.assertTrue(light_overlaps(cfg, g, existing=[]), g)
        for g in ("README.md", "docs/**", "guides/*.md"):
            with self.subTest(g=g):
                self.assertEqual(light_overlaps(cfg, g), "", g)

    def test_lead_allowed_paths_can_be_light(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'lead_light = ["README.md", "docs/**"]', 'lead_allowed = ["docs/**"]\nlead_light = ["docs/**"]'))
        cfg = config.load(self.p.root)
        self.assertEqual(light_overlaps(cfg, "docs/**"), "")
        self.assertTrue(approval.light(cfg, ["docs/guide.md"]))
        # Repeating a kit path in lead_allowed does not unprotect it.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'lead_allowed = ["docs/**"]\nlead_light = ["docs/**"]',
            'lead_allowed = ["docs/**", "skills/**", "sdlc.toml"]\nlead_light = ["docs/**", "skills/**", "sdlc.toml"]'))
        cfg = config.load(self.p.root)
        self.assertFalse(approval.light(cfg, ["skills/backend-patterns/SKILL.md"]))
        self.assertFalse(approval.light(cfg, ["sdlc.toml"]))



if __name__ == "__main__":
    unittest.main()
