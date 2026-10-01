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
            }
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)
            routes, errs = extract.code_routes(config.load(root))
            self.assertEqual(errs, [])
            self.assertEqual(sorted(routes), ["GET /api/ping", "GET /api/v1/plans", "PATCH /api/v1/plans/{}",
                                              "POST /api/v1/plans"])


class Lint(unittest.TestCase):
    def test_example_is_clean(self) -> None:
        issues = lint_repo(Repo(config.load(helpers.EXAMPLE)))
        self.assertEqual([str(i) for i in issues], [])

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
            self.assertIn("shared module app/returns.py: owner T-042-02 does not list it in files:", msgs)
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
