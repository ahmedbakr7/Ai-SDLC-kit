import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the kit on sys.path)
from sdlc import config, extract, fm, paths
from sdlc.artifacts import Repo, normalize_path
from sdlc.lint import lint_repo


class Frontmatter(unittest.TestCase):
    def test_subset(self) -> None:
        d = fm.parse('a: 1\nb: "x: y"  # c\nc: [p, "q, r", 3]\nd:\n  - one\n  - "two: 2"\ne:\nf: |\n  l1\n  l2\n')
        self.assertEqual(d, {"a": 1, "b": "x: y", "c": ["p", "q, r", 3], "d": ["one", "two: 2"],
                             "e": None, "f": "l1\nl2"})

    def test_a_leading_zero_keeps_the_text(self) -> None:
        # An abbreviated commit such as 0510682 is not the number 510682: dropping the zero
        # names a different commit.
        d = fm.parse("commit: 0510682\nn: 12\nz: 0\nm: -3\n")
        self.assertEqual(d, {"commit": "0510682", "n": 12, "z": 0, "m": -3})
        self.assertEqual(fm.parse("c: " + fm.dump_scalar("0510682") + "\n"), {"c": "0510682"})

    def test_plain_scalars_fold_across_lines_like_yaml(self) -> None:
        d = fm.parse("title: Fix the very\n  long title  # note\nfiles:\n  - a\n")
        self.assertEqual(d, {"title": "Fix the very long title", "files": ["a"]})

    def test_errors_say_how_to_fix(self) -> None:
        with self.assertRaises(fm.ParseError) as e:
            fm.parse('title: "Fix the very\n  long title"\n')
        self.assertIn("one quoted line or a '|' block", str(e.exception))

    def test_rejects_what_it_does_not_understand(self) -> None:
        for bad in ("a:\n  b: 1\n", "a: {b: 1}\n", "a: [x, [y]]\n", "a: 1\na: 2\n", "  a: 1\n", 'a: "open\n'):
            with self.subTest(bad=bad), self.assertRaises(fm.ParseError):
                fm.parse(bad)

    def test_set_scalar_keeps_other_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            src = "---\r\nid: T-1\r\nstatus: ready  # note\r\nfiles:\r\n  - a\r\n---\r\nbody\r\n"
            p.write_bytes(src.encode())
            fm.set_scalar(p, "status", "in_progress")
            fm.set_scalar(p, "blocked_by", "needs: api")
            out = p.read_bytes().decode()
            self.assertEqual(out, src.replace("status: ready  # note", "status: in_progress")
                             .replace("  - a\r\n---", '  - a\r\nblocked_by: "needs: api"\r\n---'))
            fm.set_scalar(p, "blocked_by", None)
            self.assertNotIn("blocked_by", p.read_text())


class Globs(unittest.TestCase):
    def test_dialect(self) -> None:
        cases = [("a.test.ts", "**/*.test.ts", True), ("src/x/a.test.ts", "**/*.test.ts", True),
                 ("src/a.ts", "src/*.ts", True), ("src/x/a.ts", "src/*.ts", False),
                 ("e2e/a/b.ts", "e2e/**", True), ("src/app/[id]/page.tsx", "src/app/[id]/page.tsx", True),
                 # dot-folders keep their dot; only a leading "./" is stripped
                 (".github/workflows/x.yml", ".github/**", True), ("github/x.yml", ".github/**", False),
                 (".sdlc-run/a.json", ".sdlc-run/**", True), ("src/a.ts", "./src/a.ts", True)]
        for path, pat, want in cases:
            with self.subTest(path=path, pat=pat):
                self.assertEqual(paths.match(path, pat), want)

    def test_route_normalisation(self) -> None:
        self.assertEqual(normalize_path("/v1/plans/{planId}/"), "/v1/plans/{}")
        self.assertTrue(extract.path_matches("/v1/plans/{}/response", {"/v1/plans/{}/response"}))
        self.assertTrue(extract.path_matches("/v1/plans/abc", {"/v1/plans/{}"}))
        self.assertFalse(extract.path_matches("/v1/plans", {"/api/v1/plans"}))


class V0Contracts(unittest.TestCase):
    def test_tables_section_markdown_table_declares_tables(self) -> None:
        # Hangout pilot: v0 CONTRACTS declare tables as a '## Tables' markdown table; only a
        # ```tables block was read, so every Drizzle table was reported as undeclared.
        from sdlc.artifacts import parse_contracts

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sdlc.toml").write_text("version = 1\n")
            f = root / "CONTRACTS.md"
            f.write_text("# CONTRACTS\n\n### GET /v1/me\n\n| Field | Type |\n|---|---|\n| `email` | text |\n\n"
                         "## Tables\n\n| Table | Columns |\n|---|---|\n| `accounts` | id, email |\n"
                         "| `plan_steps` | id |\n\nNo delete route.\n\n## External\n\n| Call | Request |\n"
                         "|---|---|\n| `places` | POST |\n\n```tables\nevents_log\n```\n")
            c = parse_contracts(f, config.load(root))
            self.assertEqual(sorted(c.tables), ["accounts", "events_log", "plan_steps"])
            self.assertEqual([r.key for r in c.routes], ["GET /v1/me"])


class NextjsTestForbid(unittest.TestCase):
    """The nextjs profile's banned test patterns, on shapes found in a real product."""

    def flagged(self, src: str) -> bool:
        import re
        import tomllib

        prof = tomllib.loads((helpers.KIT / "profiles" / "nextjs.toml").read_text(encoding="utf-8"))
        return any(re.search(r["regex"], src, re.M) for r in prof["tests"]["forbid"])

    def test_duplication_scans_production_code_only(self) -> None:
        import shlex
        import tomllib

        prof = tomllib.loads((helpers.KIT / "profiles" / "nextjs.toml").read_text(encoding="utf-8"))
        words = shlex.split(prof["commands"]["duplication"])
        # Hangout pilot: --exitCode 1 fails on any clone at all, so --threshold never decided.
        self.assertNotIn("--exitCode", words)
        self.assertIn("--threshold", words)
        ignored = words[words.index("--ignore") + 1].split(",")
        for g in prof["tests"]["globs"]:
            if g.startswith("**/*."):  # unit test files live beside the code jscpd scans
                with self.subTest(glob=g):
                    self.assertTrue(any(paths.match(g.replace("**/*.", "src/x."), i) for i in ignored), g)

    def test_source_reads_are_flagged(self) -> None:
        for src in ('const panel = readFileSync(join(root, "src/components/join-panel.tsx"), "utf8");',
                    'const page = readFileSync(\n  join(root, "src/app/join/[token]/page.tsx"),\n  "utf8",\n);',
                    # Hangout pilot: a helper wrapping readFileSync hid two whole test files.
                    'const tokens = read("src/app/tokens.css");',
                    "const layout = readSource('./src/app/layout.tsx');"):
            with self.subTest(src=src):
                self.assertTrue(self.flagged(src))

    def test_one_source_read_is_one_finding(self) -> None:
        import re
        import tomllib

        prof = tomllib.loads((helpers.KIT / "profiles" / "nextjs.toml").read_text(encoding="utf-8"))
        src = 'const s = readFileSync("src/app/page.tsx", "utf8");'
        self.assertEqual(sum(bool(re.search(r["regex"], src)) for r in prof["tests"]["forbid"]), 1)

    def test_behaviour_tests_and_fixture_reads_pass(self) -> None:
        for src in ('const sql = readFileSync(resolve(process.cwd(), "drizzle/0001_init.sql"), "utf8");',
                    'render(<JoinPanel planId="p1" />);',
                    'const res = await fetch("/api/v1/plans");',
                    'const data = readJson("fixtures/plan.json");'):
            with self.subTest(src=src):
                self.assertFalse(self.flagged(src))


class BaselineVersions(unittest.TestCase):
    """ADR-0002 step 4a: version 2 stores a count per key; version 1 is still read."""

    def test_version_2_round_trips_counts(self) -> None:
        from sdlc import baseline

        checks = {"typecheck": ["a.ts: TS1", "a.ts: TS1", "b.ts: TS2"], "lint": []}
        text = baseline.dump(checks)
        self.assertEqual(json.loads(text), {"version": 2, "checks": {"typecheck": {"a.ts: TS1": 2, "b.ts: TS2": 1}}})
        self.assertEqual(sorted(baseline.parse(text)["typecheck"]), checks["typecheck"])

    def test_version_1_lists_count_once_per_line(self) -> None:
        from sdlc import baseline

        v1 = json.dumps({"version": 1, "checks": {"contracts": ["x", "x"], "scope": ["never"]}})
        self.assertEqual(baseline.parse(v1), {"contracts": ["x", "x"]})

    def test_a_count_that_is_not_a_positive_integer_carries_nothing(self) -> None:
        from sdlc import baseline

        v2 = json.dumps({"version": 2, "checks": {"lint": {"a": 0, "b": -1, "c": True, "d": "3", "e": 1.5, "f": 2,
                                                            "g": baseline.MAX_COUNT + 1, "h": baseline.MAX_COUNT}}})
        parsed = baseline.parse(v2)["lint"]  # above the cap: not expanded at all
        self.assertEqual(parsed.count("f"), 2)
        self.assertEqual(parsed.count("h"), baseline.MAX_COUNT)
        self.assertEqual(set(parsed), {"f", "h"})

    def test_a_renamed_path_is_replaced_only_where_it_stands_whole(self) -> None:
        from sdlc import baseline

        moved = {"app/a.py": "app/b.py"}
        keys = ["app/a.py: TS1", "client calls /v1/x at app/a.py; y", "app/a.pyi: TS1",
                "xapp/a.py: TS1", "app/a.py.bak/c.py: TS1", "test_a_py_works"]
        self.assertEqual(baseline.remap({"lint": keys}, moved)["lint"],
                         ["app/b.py: TS1", "client calls /v1/x at app/b.py; y", "app/a.pyi: TS1",
                          "xapp/a.py: TS1", "app/a.py.bak/c.py: TS1", "test_a_py_works"])


class BaselineKeys(unittest.TestCase):
    """Baseline keys must survive edits that only move a known failure to another line."""

    def test_tool_findings_ignore_line_numbers(self) -> None:
        from sdlc import baseline

        before = ("src/a.test.ts(108,94): error TS1501: This regular expression flag is only available...\n"
                  "src/db/schema.test.ts(141,47): error TS2345: Argument of type 'PgEnum'...\n"
                  "app/x.py:12: error: Incompatible types  [arg-type]\n"
                  "app/y.py:3:1: F401 'os' imported but unused\n")
        after = before.replace("(108,94)", "(120,9)").replace("(141,47)", "(150,47)").replace(":12:", ":40:")
        self.assertEqual(baseline.tool_findings(before), baseline.tool_findings(after))
        self.assertEqual(baseline.tool_findings(before), ["src/a.test.ts: TS1501", "src/db/schema.test.ts: TS2345",
                                                          "app/x.py: arg-type", "app/y.py: F401"])

    def test_detail_findings_ignore_line_numbers(self) -> None:
        from sdlc import baseline

        self.assertEqual(
            baseline.detail_findings(["src/components/a.test.tsx:184: test reads source text instead of exercising behaviour",
                                      "client calls /v1/me at src/components/account-gate.tsx:178; CONTRACTS declares it",
                                      "WARN  tickets/T-1.md: risk: high ticket has no accepted_by"]),
            ["src/components/a.test.tsx: test reads source text instead of exercising behaviour",
             "client calls /v1/me at src/components/account-gate.tsx; CONTRACTS declares it"])

    def test_compare_counts_repeats(self) -> None:
        from sdlc import baseline

        known = ["f.ts: TS2345", "f.ts: TS2345"]
        self.assertEqual(baseline.compare(known, ["f.ts: TS2345"] * 3), (["f.ts: TS2345"], []))
        self.assertEqual(baseline.compare(known, ["f.ts: TS2345"]), ([], ["f.ts: TS2345"]))


class NextjsRoutes(unittest.TestCase):
    def test_app_router_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sdlc.toml").write_text('profile = "nextjs"\n')
            files = {
                "src/app/api/v1/plans/route.ts": "export async function GET() {}\nexport const POST = h;",
                "src/app/api/v1/plans/[planId]/route.ts": "async function PATCH() {}\nexport { PATCH, helper };",
                "src/app/(marketing)/api/ping/route.ts": "export function GET() {}",
                "src/app/_private/route.ts": "export function GET() {}",
                "src/app/api/v1/plans/page.tsx": "export default function P() {}",
                "src/app/page.tsx": "export default function Home() {}",
                "src/app/(app)/plans/[planId]/page.tsx": "export default function P() {}",
                "src/app/[locale]/settings/page.mdx": "# Settings",
                "src/app/@modal/login/page.tsx": "export default function M() {}",
                "src/app/plans/_parts/page.tsx": "export default function Hidden() {}",
            }
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)
            routes, pages, errs = extract.code_surface(config.load(root))
            self.assertEqual(errs, [])
            self.assertEqual(sorted(routes), ["GET /api/ping", "GET /api/v1/plans", "PATCH /api/v1/plans/{}",
                                              "POST /api/v1/plans"])
            self.assertEqual(sorted(pages), ["/", "/api/v1/plans", "/plans/{}", "/{}/settings"])


class Lint(unittest.TestCase):
    def test_example_is_clean(self) -> None:
        issues = lint_repo(Repo(config.load(helpers.EXAMPLE)))
        self.assertEqual([str(i) for i in issues], [])

    def test_legacy_v0_ticket_skips_v1_review_and_size_rules_only(self) -> None:
        # Hangout pilot: 30 tickets shipped under kit v0 (reviews/pr-N.md) failed lint for
        # lacking a v1 review and for v1 size limits. `legacy: v0` exempts exactly those.
        p = helpers.ProductRepo()
        try:
            rel = "tickets/T-042-01-returns-api.md"
            (p.root / "reviews" / "T-042-01.md").unlink()
            extra = "".join(f'  - "AC-{n}: the order list answers case {n} as documented"\n' for n in range(5, 10))
            lines = p.read(rel).split("\n")
            i = max(k for k, ln in enumerate(lines) if ln.startswith('  - "AC-'))
            lines[i + 1:i + 1] = extra.rstrip("\n").split("\n")
            p.write(rel, "\n".join(lines))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertIn("status done needs reviews/T-042-01.md", msgs)
            self.assertIn("acceptance criteria > 8", msgs)
            p.write(rel, p.read(rel).replace("status: done\n", "status: done\nlegacy: v0\n", 1))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertNotIn("T-042-01", msgs)
            # Only shipped tickets, and only the v0 marker.
            p.write(rel, p.read(rel).replace("status: done\n", "status: ready\n", 1))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertIn("legacy: v0 is only for a ticket that shipped (status: done) under kit v0", msgs)
            p.write(rel, p.read(rel).replace("status: ready\nlegacy: v0", "status: done\nlegacy: yes", 1))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertIn("legacy must be v0, got 'yes'", msgs)
        finally:
            p.close()

    def test_migrate_marks_done_tickets_without_a_v1_review_legacy(self) -> None:
        from sdlc import cli

        p = helpers.ProductRepo()
        try:
            (p.root / "reviews" / "T-042-01.md").unlink()
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["--root", str(p.root), "migrate"]), 0)
            self.assertIn("tickets/T-042-01-returns-api.md: marked legacy: v0", out.getvalue())
            self.assertIn("status: done\nlegacy: v0\n", p.read("tickets/T-042-01-returns-api.md"))
            self.assertNotIn("legacy", p.read("tickets/T-042-02-order-page.md"))  # not done
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cli.main(["--root", str(p.root), "migrate"])  # idempotent
            self.assertNotIn("marked", out.getvalue())
        finally:
            p.close()

    def test_ticket_errors(self) -> None:
        p = helpers.ProductRepo()
        try:
            rel = "tickets/T-042-02-order-page.md"
            t = p.read(rel).replace('"AC-2: an order with no returns renders no Returns heading"', "works")
            t = t.replace("  - F-042-6\n", "  - F-999-1\n").replace("  - /orders/{id}\n", "  - GET /nope\n")
            t = t.replace("depends_on:\n  - T-042-01", "depends_on:\n  - T-042-09")
            p.write(rel, t)
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            for want in ("must be 'AC-<n>", "F-999-1 is not defined", "'GET /nope' is not declared",
                         "T-042-09 does not exist"):
                self.assertIn(want, msgs)
        finally:
            p.close()

    def test_one_owner_per_shared_concern(self) -> None:
        p = helpers.ProductRepo()
        try:
            # Both tickets open and unordered, both writing the route table.
            t1 = "tickets/T-042-01-returns-api.md"
            p.write(t1, p.read(t1).replace("status: done", "status: in_review"))
            t2 = "tickets/T-042-02-order-page.md"
            p.write(t2, p.read(t2).replace("depends_on:\n  - T-042-01", "depends_on: []"))
            # The plan names an owner that never creates the module.
            plan = "arch/plan-042-return-status.md"
            p.write(plan, p.read(plan).replace("| `app/returns.py` | T-042-01 |", "| `app/returns.py` | T-042-02 |"))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertIn("T-042-01 and T-042-02 both write app/server.py but neither depends on the other", msgs)
            self.assertIn("shared module app/returns.py: owner T-042-02 does not list it in areas:", msgs)
        finally:
            p.close()

    def test_contract_owner_must_be_a_ticket(self) -> None:
        p = helpers.ProductRepo()
        try:
            p.write("arch/CONTRACTS.md", p.read("arch/CONTRACTS.md").replace("owner=T-042-02", "owner=T-042-20"))
            msgs = "\n".join(str(i) for i in lint_repo(Repo(config.load(p.root))))
            self.assertIn("page /orders/{id}: owner=T-042-20 is not a ticket", msgs)
        finally:
            p.close()

    def test_build_prompt_lists_shared_modules_to_import(self) -> None:
        from sdlc import prompt

        text = prompt.render(config.load(helpers.EXAMPLE), "build", "T-042-02")
        self.assertIn("## Shared modules (import these; never re-implement them)", text)
        self.assertIn("| `app/returns.py` | T-042-01 | read returns for an order; the only place that knows "
                      "the data source | exists: import it |", text)


if __name__ == "__main__":
    unittest.main()
