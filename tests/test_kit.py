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

    def test_the_changelog_names_the_current_version(self) -> None:
        # A release is a tag plus a CHANGELOG entry; bumping __version__ without one fails here.
        from sdlc import __version__

        headings = re.findall(r"^## (v\S+) \(\d{4}-\d{2}-\d{2}\)$", (KIT / "CHANGELOG.md").read_text(encoding="utf-8"),
                              re.MULTILINE)
        self.assertIn(f"v{__version__}", headings)
        self.assertEqual(headings[0], f"v{__version__}", "the newest entry is the current version")

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

    def test_shell_launchers_are_committed_executable(self) -> None:
        # Authored on Windows, bin/sdlc was committed 100644: `.sdlc/bin/sdlc` (and the
        # shipped CI workflow) failed with "Permission denied" on Linux and macOS.
        from helpers import git

        for rel in ("bin/sdlc", "scripts/update-kit.sh"):
            with self.subTest(file=rel):
                mode = git(KIT, "ls-files", "-s", "--", rel).split()[0]
                self.assertEqual(mode, "100755", f"{rel}: git update-index --chmod=+x {rel}")

    def test_ci_workflow_can_clone_a_private_kit_without_leaking_the_token(self) -> None:
        # Hangout pilot: github.token reads only the product repo, so checkout of a private
        # .sdlc submodule failed with "repository not found" and the gate never ran.
        wf = (KIT / "adapters" / "github" / "sdlc.yml").read_text(encoding="utf-8")
        self.assertIn("token: ${{ secrets.SDLC_KIT_TOKEN || github.token }}", wf)
        self.assertIn("persist-credentials: false", wf)
        self.assertIn("submodules: true", wf)
        # upload-artifact v4 skips dot-folders unless told otherwise: .sdlc-run/ was never uploaded.
        self.assertIn("include-hidden-files: true", wf)
        self.assertIn("if: ${{ !cancelled() }}", wf)
        self.assertIn("github.event_name == 'pull_request' && !cancelled()", wf)

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

    def test_a_play_prompt_leaves_out_the_other_plays_skills(self) -> None:
        # Pilot finding 5: the ticket lists `skills: [build, frontend-patterns]`, and the test
        # play's prompt carried the build skill's instructions next to its own.
        from sdlc import prompt

        text = prompt.render(config.load(EXAMPLE), "test", "T-042-02")
        self.assertIn("## Play skill: test", text)
        self.assertIn("## Skill: frontend-patterns", text)
        self.assertNotIn("## Skill: build", text)
        self.assertNotIn("# Play: build", text)

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
                        ".github/workflows/sdlc-approval.yml", ".github/workflows/sdlc-approval-review.yml",
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
                self.assertNotEqual(cli.main(["--root", d, "doctor"]), 0)
            # Unit tests on stubs never prove a route: the nextjs profile wants e2e over HTTP.
            self.assertIn("no real-stack suite: tests.real_stack is e2e, but commands.e2e is not set",
                          out.getvalue())
            toml = (root / "sdlc.toml").read_text().replace(
                "[commands]\n", '[commands]\ne2e = "npx --no-install playwright test --reporter=junit {junit}"\n', 1)
            (root / "sdlc.toml").write_text(toml)
            (root / "node_modules" / ".bin" / "playwright").write_text("")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--root", d, "doctor"]), 0, out.getvalue())


    def test_doctor_resolves_npm_flags_and_npx_downloads(self) -> None:
        # Hangout pilot: `npm run --silent lint` was read as script "--silent", and
        # `npx --yes jscpd@4.3.0` as a binary named "jscpd@4.3.0" that had to be installed.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "package.json").write_text('{"scripts": {"lint": "tsc"}}')
            self.assertEqual(cli._unresolvable(root, "npm run --silent lint"), "")
            self.assertEqual(cli._unresolvable(root, "npm --silent run lint"), "")
            self.assertIn("no script 'fmt'", cli._unresolvable(root, "npm run --silent fmt"))
            self.assertEqual(cli._unresolvable(root, "npx --yes jscpd@4.3.0 src"), "")
            self.assertEqual(cli._unresolvable(root, "npx -y @scope/tool@1.2.0 src"), "")
            # Without --yes, npx needs the local install, looked up by package name.
            self.assertIn("jscpd is not installed (no node_modules/.bin/jscpd)",
                          cli._unresolvable(root, "npx --no-install jscpd@4.3.0 src"))
            (root / "node_modules" / ".bin").mkdir(parents=True)
            (root / "node_modules" / ".bin" / "jscpd").write_text("")
            self.assertEqual(cli._unresolvable(root, "npx --no-install jscpd@4.3.0 src"), "")

if __name__ == "__main__":
    unittest.main()
