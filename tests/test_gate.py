"""Each check must catch the failure it exists for. These are the defects that shipped
in a real product built without them (routes mounted at the wrong prefix, tests that
read source text, "green" suites that ran nothing, AC with no test, edited ADRs)."""
import json
import unittest

from helpers import ProductRepo


class GateCatches(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()
        # Put T-042-02 in progress so build-gate checks apply to it.
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertEqual(code, 0, out)
        self.p.commit("start T-042-02")

    def tearDown(self) -> None:
        self.p.close()

    def gate(self, play: str, *checks: str, ticket: str | None = "T-042-02") -> dict:
        args = ["gate", play] + ([ticket] if ticket else []) + ["--only", ",".join(checks)]
        self.code, self.out = self.p.sdlc(*args)
        name = f"{ticket}.{play}.json" if ticket else f"{play}.json"
        for d in ("evidence", ".sdlc-run"):
            f = self.p.root / d / name
            if f.is_file():
                ev = json.loads(f.read_text(encoding="utf-8"))
                return {c["name"]: c for c in ev["checks"]}
        self.fail(self.out)

    def apply_solution(self) -> None:
        from helpers import FIXTURES
        import shutil

        sol = FIXTURES / "solutions" / "build-T-042-02"
        for f in sol.rglob("*"):
            if f.is_file():
                dest = self.p.root / f.relative_to(sol)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)

    def test_route_in_code_but_not_in_contracts(self) -> None:
        s = self.p.read("app/server.py").replace(
            '("api", "GET", "/api/orders/{id}/returns", get_returns),',
            '("api", "GET", "/api/orders/{id}/returns", get_returns),\n    ("api", "DELETE", "/api/orders/{id}", get_returns),')
        self.p.write("app/server.py", s)
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("DELETE /api/orders/{}", "\n".join(c["details"]))

    def test_router_mounts_contract_route_under_wrong_prefix(self) -> None:
        # The contract says /api/orders/..., the code serves /api/v1/orders/...
        s = self.p.read("app/server.py").replace('"/api/orders/{id}/returns"', '"/api/v1/orders/{id}/returns"')
        self.p.write("app/server.py", s)
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail")
        details = "\n".join(c["details"])
        self.assertIn("GET /api/v1/orders/{}/returns", details)

    def test_client_calls_a_path_no_contract_serves(self) -> None:
        self.p.write("app/static/app.js", 'export const load = (id) => fetch(`/v1/orders/${id}/returns`);\n')
        with open(self.p.root / "sdlc.toml", "a", encoding="utf-8") as f:
            f.write('\n[client]\npatterns = [\'\'\'fetch\\(\\s*[`"\'](?P<path>/[^`"\'\\s?#]*)\'\'\']\n'
                    'globs = ["app/static/**"]\nprefix = "/"\n')
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("client calls /v1/orders/{}/returns at app/static/app.js:1", "\n".join(c["details"]))

    def test_smoke_fails_when_a_contract_page_is_not_served(self) -> None:
        # T-042-02 is in progress, so its page must answer; the page is not built yet.
        c = self.gate("build", "smoke")["smoke"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("page /orders/{id}", "\n".join(c["details"]))

    def test_smoke_passes_once_built(self) -> None:
        self.apply_solution()
        c = self.gate("build", "smoke")["smoke"]
        self.assertEqual(c["status"], "pass", c)

    def test_ac_without_a_passing_test(self) -> None:
        self.apply_solution()
        t = self.p.read("app/test_pages.py").replace('"""T-042-02/AC-3"""', '"""no tag"""')
        self.p.write("app/test_pages.py", t)
        c = self.gate("build", "unit", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("T-042-02/AC-3: missing", c["details"])

    def test_ac_with_a_failing_test(self) -> None:
        self.apply_solution()
        self.p.write("app/pages.py", self.p.read("app/pages.py").replace('"Unknown"', '"???"'))
        checks = self.gate("build", "unit", "ac-coverage")
        self.assertEqual(checks["unit"]["status"], "fail")
        self.assertIn("T-042-02/AC-3: failed", checks["ac-coverage"]["details"])

    def lead_config(self, old: str, new: str) -> None:
        """A config change the lead committed to the base branch (ticket gates ignore uncommitted ones)."""
        text = self.p.read("sdlc.toml")
        self.assertIn(old, text)
        self.p.write("sdlc.toml", text.replace(old, new))
        self.p.commit("lead: config")

    def test_suite_that_runs_nothing_is_not_green(self) -> None:
        self.lead_config("--start app", "--start nowhere")
        c = self.gate("build", "unit")["unit"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("ran 0 tests", c["summary"])

    def test_required_command_missing_is_a_failure_not_a_skip(self) -> None:
        # An empty command overrides the profile default: typecheck is now "not configured".
        self.lead_config('typecheck = "python tools/lint.py --types"', 'typecheck = ""')
        c = self.gate("build", "typecheck")["typecheck"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("not configured", c["summary"])

    def test_unit_command_without_junit_cannot_prove_ac(self) -> None:
        self.apply_solution()
        self.lead_config('unit = "python tools/junit.py --start app --out {junit}"',
                         'unit = "python -m unittest discover -s app -t ."')
        c = self.gate("build", "unit", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("cannot be proven", c["summary"])

    def test_skipped_and_source_reading_tests(self) -> None:
        self.apply_solution()
        t = self.p.read("app/test_pages.py").replace("    def test_no_returns_no_heading",
                                                     "    @unittest.skip('later')\n    def test_no_returns_no_heading")
        self.p.write("app/test_pages.py", t)
        c = self.gate("build", "test-quality")["test-quality"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("app/test_pages.py", "\n".join(c["details"]))

    def test_file_outside_ticket_scope(self) -> None:
        self.apply_solution()
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# drive-by edit\n")
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside build write set: app/returns.py", c["details"])

    def test_agent_cannot_reconfigure_its_own_gate(self) -> None:
        # The agent drops `scope` from the build gate so its stray file goes unnoticed.
        self.apply_solution()
        self.p.write("app/stray.py", "x = 1\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\nbuild = ["artifacts", "unit"]\n')
        checks = self.gate("build", "scope", "unit")  # KeyError if the branch's plan was obeyed
        self.assertEqual(checks["scope"]["status"], "fail")
        details = "\n".join(checks["scope"]["details"])
        self.assertIn("outside build write set: app/stray.py", details)
        self.assertIn("outside build write set: sdlc.toml", details)
        self.assertIn("differs from main", details)

    def test_tests_beside_listed_files_are_in_scope(self) -> None:
        self.apply_solution()
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)

    def test_accepted_adr_edit(self) -> None:
        self.p.write("decisions/ADR-0001-stack.md", self.p.read("decisions/ADR-0001-stack.md") + "\nChanged my mind.\n")
        c = self.gate("ci", "immutable", ticket=None)["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("accepted ADR edited", "\n".join(c["details"]))

    def test_weakening_an_ac_without_the_spec(self) -> None:
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("and the page still answers 200", "if convenient"))
        c = self.gate("ci", "immutable", ticket=None)["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("AC-3 reworded", "\n".join(c["details"]))

    def test_full_build_gate_passes_on_the_reference_solution(self) -> None:
        self.apply_solution()
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(self.code, 0, self.out)


if __name__ == "__main__":
    unittest.main()
