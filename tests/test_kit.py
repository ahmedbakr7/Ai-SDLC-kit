"""The kit's own files stay consistent with the CLI (skills, templates, docs, catalog)."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from helpers import KIT, EXAMPLE
from sdlc import cli, config, fm


class KitConsistency(unittest.TestCase):
    def test_every_skill_has_matching_name_and_description(self) -> None:
        for p in sorted((KIT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=p.parent.name):
                data, body = fm.load(p)
                self.assertEqual(data.get("name"), p.parent.name)
                self.assertGreater(len(str(data.get("description", ""))), 40)
                self.assertTrue(body.strip())

    def test_every_play_has_a_skill(self) -> None:
        from sdlc.prompt import LEAD_PLAYS, TICKET_PLAYS

        for play in (*TICKET_PLAYS, *LEAD_PLAYS):
            self.assertTrue((KIT / "skills" / play / "SKILL.md").is_file(), play)

    def test_templates_parse(self) -> None:
        for name in ("intent", "spec", "plan", "adr", "ticket", "review", "incident"):
            with self.subTest(template=name):
                data, _ = fm.load(KIT / "templates" / f"{name}.md")
                self.assertTrue(data)

    def test_prompt_templates_exist(self) -> None:
        from sdlc.prompt import LEAD_PLAYS

        for tpls in LEAD_PLAYS.values():
            for t in tpls:
                self.assertTrue((KIT / t).is_file(), t)

    def test_docs_only_mention_real_subcommands(self) -> None:
        sub = set(cli.build_parser()._subparsers._group_actions[0].choices)
        for md in [*KIT.glob("*.md"), *KIT.glob("adapters/*.md"), *KIT.glob("skills/**/*.md"),
                   *KIT.glob("examples/returns-app/*.md")]:
            for m in re.finditer(r"(?<![\w.-])sdlc (?:--root \S+ )?([a-z]+)\b", md.read_text(encoding="utf-8")):
                if m.group(1) in ("play", "kit", "gate", "run") or m.group(1) in sub:
                    continue
                self.fail(f"{md.relative_to(KIT)} mentions unknown `sdlc {m.group(1)}`")

    def test_catalog_entries_are_complete(self) -> None:
        cat = json.loads((KIT / "skills" / "vendor" / "catalog.json").read_text(encoding="utf-8"))
        for key, e in cat["skills"].items():
            with self.subTest(key=key):
                self.assertTrue(e["source"].startswith("https://"))
                for k in ("path", "license", "plays", "use"):
                    self.assertIn(k, e)

    def test_profiles_load(self) -> None:
        for p in (KIT / "profiles").glob("*.toml"):
            with self.subTest(profile=p.stem):
                self.assertIn("commands", config.load_profile(p.stem))

    def test_build_prompt_is_complete(self) -> None:
        from sdlc import prompt

        text = prompt.render(config.load(EXAMPLE), "build", "T-042-02")
        for want in ("# sdlc play: BUILD T-042-02", "## Operating rules", "## Play skill: build",
                     "F-042-5", "/orders/{id}", "## Skill: frontend-patterns", "`app/pages.py`",
                     "T-042-02/AC-3", "sdlc gate build T-042-02"):
            self.assertIn(want, text)

    def test_init_scaffolds_a_product_that_doctor_explains(self) -> None:
        import contextlib
        import io
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--root", d, "init", "--profile", "nextjs"]), 0)
                code = cli.main(["--root", d, "doctor"])
            root = Path(d)
            for rel in ("sdlc.toml", "AGENTS.md", "CLAUDE.md", ".github/workflows/sdlc.yml",
                        "skills/backend-patterns/SKILL.md", "skills.lock.json", ".claude/commands/sdlc-build.md"):
                self.assertTrue((root / rel).is_file(), rel)
            self.assertIn('profile = "nextjs"', (root / "sdlc.toml").read_text())
            # The profile supplies commands, but nothing is installed: every check would fail.
            self.assertNotEqual(code, 0, out.getvalue())
            for tool in ("eslint", "tsc", "vitest", "next", "jscpd"):
                self.assertIn(f"{tool} is not installed", out.getvalue())
            for tool in ("eslint", "tsc", "vitest", "next", "jscpd"):
                (root / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
                (root / "node_modules" / ".bin" / tool).write_text("")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--root", d, "doctor"]), 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
