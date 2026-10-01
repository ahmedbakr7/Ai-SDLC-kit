"""Each check must catch the failure it exists for. These are the defects that shipped
in a real product built without them (routes mounted at the wrong prefix, tests that
read source text, "green" suites that ran nothing, AC with no test, edited ADRs)."""
import json
import unittest

from helpers import FIXTURES as FIXTURES_DIR, ProductRepo


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
        f = self.p.root / ".sdlc-run" / name  # --only runs are partial: never under evidence/
        if f.is_file():
            ev = json.loads(f.read_text(encoding="utf-8"))
            return {c["name"]: c for c in ev["checks"]}
        self.fail(self.out)

    def apply_solution(self, name: str = "build-T-042-02") -> None:
        from helpers import FIXTURES
        import shutil

        sol = FIXTURES / "solutions" / name
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

    def test_page_in_code_but_not_in_contracts(self) -> None:
        # The route extractor command may report pages as 'PAGE /path' lines.
        self.p.write("tools/surface.py", "import runpy, sys\nrunpy.run_path('tools/routes.py')\n"
                     "print('PAGE /orders/{id}')\nprint('PAGE /admin')\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('command = "python tools/routes.py"',
                                                                   'command = "python tools/surface.py"'))
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["details"], ["page in code but not in CONTRACTS: /admin (routes.command)"])

    def test_options_probe_requires_the_method_in_allow(self) -> None:
        # mutating_probe = "options" never sends the write; a router that cannot say it
        # serves DELETE (here: no OPTIONS support at all) fails instead of passing.
        self.p.write("tools/surface.py", "import runpy\nrunpy.run_path('tools/routes.py')\n"
                     "print('DELETE /api/orders/{id}/returns')\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('command = "python tools/routes.py"',
                     'command = "python tools/surface.py"').replace('ready_path = "/"',
                                                                   'ready_path = "/"\nmutating_probe = "options"'))
        self.p.write("arch/CONTRACTS.md", self.p.read("arch/CONTRACTS.md").replace(
            "GET /api/orders/{id}/returns  owner=T-042-01  sample=/api/orders/ord_1/returns",
            "GET /api/orders/{id}/returns  owner=T-042-01  sample=/api/orders/ord_1/returns\n"
            "DELETE /api/orders/{id}/returns  owner=T-042-01  sample=/api/orders/ord_1/returns"))
        c = self.gate("ci", "smoke", ticket=None)["smoke"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("DELETE /api/orders/{}/returns: OPTIONS answered 501 with Allow: - "
                      "-> the router does not serve DELETE here", c["details"])

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

    def test_ac_proven_only_by_a_tautology(self) -> None:
        # The real AC-3 test loses its tag; a test that asserts nothing about the work takes it.
        self.apply_solution()
        self.p.write("app/test_pages.py", self.p.read("app/test_pages.py").replace('"""T-042-02/AC-3"""', '"""no tag"""'))
        self.p.write("app/test_server.py", 'import unittest\n\n\nclass Unknown(unittest.TestCase):\n'
                     '    def test_unknown_state(self) -> None:\n        """T-042-02/AC-3"""\n'
                     '        self.assertTrue(True)\n')
        pages = self.p.read("app/pages.py")
        checks = self.gate("build", "unit", "ac-coverage", "ac-red")
        self.assertEqual(checks["ac-coverage"]["status"], "pass")  # the tag alone satisfies coverage
        self.assertEqual(checks["ac-red"]["status"], "fail")
        self.assertEqual(len(checks["ac-red"]["details"]), 1)
        self.assertIn("T-042-02/AC-3: passes without this ticket's code", checks["ac-red"]["details"][0])
        self.assertEqual(self.p.read("app/pages.py"), pages)  # reverted files are restored
        self.assertFalse((self.p.root / ".sdlc-run" / "red-backup").exists())

    def test_ac_red_passes_on_the_reference_solution(self) -> None:
        self.apply_solution()
        c = self.gate("build", "unit", "ac-red")["ac-red"]
        self.assertEqual(c["status"], "pass", c)

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

    def build_and_commit(self) -> str:
        """The reference build, gated and committed the way the runner does it. Returns the proven commit."""
        from helpers import git

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.apply_solution()
        self.p.commit("build T-042-02")
        code, out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_review", "--as", "build")[0], 0)
        self.p.commit("evidence T-042-02: build gate pass")  # one commit, as `sdlc run` does
        return json.loads(self.p.read("evidence/T-042-02.build.json"))["commit"]

    def test_partial_gate_run_is_not_evidence(self) -> None:
        # `--only lint` passing must not leave a passing evidence/ file that review and trace trust.
        code, out = self.p.sdlc("gate", "build", "T-042-02", "--only", "lint")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.p.root / "evidence" / "T-042-02.build.json").exists())
        ev = json.loads(self.p.read(".sdlc-run/T-042-02.build.json"))
        self.assertTrue(ev["partial"])

    def test_test_play_cannot_rewrite_build_evidence(self) -> None:
        # The test agent commits a production change, then points the build evidence at that
        # commit so the test play's "changed since the proven build" diff no longer shows it.
        from helpers import git

        self.build_and_commit()
        start = git(self.p.root, "rev-parse", "HEAD").strip()  # what `sdlc run` records before the agent
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# production change in a test play\n")
        self.p.commit("sneak")
        ev = json.loads(self.p.read("evidence/T-042-02.build.json"))
        ev["commit"] = git(self.p.root, "rev-parse", "HEAD").strip()
        self.p.write("evidence/T-042-02.build.json", json.dumps(ev, indent=2))
        self.p.commit("forge")
        self.code, self.out = self.p.sdlc("gate", "test", "T-042-02", "--since", start, "--only", "scope")
        c = json.loads(self.p.read(".sdlc-run/T-042-02.test.json"))["checks"][0]
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside test write set: evidence/T-042-02.build.json", c["details"])
        self.assertIn("outside test write set: app/returns.py", c["details"])

    def test_review_must_name_the_proven_commit_exactly(self) -> None:
        proven = self.build_and_commit()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        for commit, want in ((proven[:3], "fail"), ("0000000", "fail"), (proven[:7], "pass"), (proven, "pass")):
            with self.subTest(commit=commit):
                self.p.write("reviews/T-042-02.md", review.replace("{commit}", commit))
                c = self.gate("review", "review-file")["review-file"]
                self.assertEqual(c["status"], want, c)

    def test_review_rejects_test_evidence_older_than_the_build(self) -> None:
        # build -> test -> rebuild: the old test evidence no longer describes the code.
        from helpers import git

        first = self.build_and_commit()
        ev = json.loads(self.p.read("evidence/T-042-02.build.json"))
        ev.update(play="test")
        self.p.write("evidence/T-042-02.test.json", json.dumps(ev, indent=2))
        self.p.commit("test evidence at the first build")
        self.p.write("app/pages.py", self.p.read("app/pages.py") + "\n# rebuild after review\n")
        self.p.commit("rebuild")
        self.assertEqual(self.p.sdlc("gate", "build", "T-042-02")[0], 0)
        self.p.commit("evidence: rebuild")
        latest = git(self.p.root, "rev-parse", "HEAD~1").strip()
        self.assertNotEqual(first, latest)
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        self.p.write("reviews/T-042-02.md", review.replace("{commit}", latest))
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("test evidence is older than the build evidence", "\n".join(c["details"]))

    def test_rebuild_keeps_but_may_not_edit_the_test_plays_files(self) -> None:
        self.build_and_commit()
        self.p.write("tests/test_order_page_http.py", '"""T-042-02 integration tests"""\n')
        self.p.write("evidence/T-042-02.test.json", self.p.read("evidence/T-042-02.build.json"))
        self.p.commit("test play")
        self.p.write("app/pages.py", self.p.read("app/pages.py") + "\n# rebuild\n")
        self.assertEqual(self.gate("build", "scope")["scope"]["status"], "pass")
        self.p.write("tests/test_order_page_http.py", '"""weakened by the builder"""\n')
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside build write set: tests/test_order_page_http.py", c["details"])

    def test_play_cannot_mark_its_own_ticket_done(self) -> None:
        self.build_and_commit()
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("status: in_review", "status: done"))
        c = self.gate("test", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn(f"{rel}: status in_review -> done is not a move the test play may make", c["details"])
        # ... and with no approving review, `done` is an artifact error for every gate, CI included.
        a = self.gate("ci", "artifacts", ticket=None)["artifacts"]
        self.assertEqual(a["status"], "fail")
        self.assertIn("status done needs reviews/T-042-02.md with verdict: approve", "\n".join(a["details"]))

    def test_ci_reproves_every_shipped_ticket(self) -> None:
        # T-042-01 is done. A later change (e.g. another ticket's build editing a shared test
        # file) drops the tag from one of its AC tests. Before: gate ci stayed green.
        c = self.gate("ci", "unit", "ac-coverage", ticket=None)["ac-coverage"]
        self.assertEqual(c["status"], "pass", c)
        self.assertIn("all 4 AC of 1 ticket(s)", c["summary"])
        self.p.write("app/test_returns.py", self.p.read("app/test_returns.py").replace('"""T-042-01/AC-4"""', '"""404"""'))
        c = self.gate("ci", "unit", "ac-coverage", ticket=None)["ac-coverage"]
        self.assertEqual(c["status"], "fail")
        self.assertEqual(c["details"], ["T-042-01/AC-4: missing"])

    def test_build_may_move_its_ticket_to_in_review(self) -> None:
        self.build_and_commit()  # ready -> in_progress -> in_review, both build moves
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)

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

    def test_unrelated_spec_edit_does_not_license_an_ac_change(self) -> None:
        rel, spec = "tickets/T-042-02-order-page.md", "design/spec-042-return-status.md"
        self.p.write(rel, self.p.read(rel).replace("and the page still answers 200", "if convenient"))
        # F-042-1 is not one of T-042-02's requirements: before, any spec edit let the AC change.
        self.p.write(spec, self.p.read(spec).replace("each with `id` and `state`.", "each with `id`, `state`."))
        c = self.gate("ci", "immutable", ticket=None)["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("AC-3 reworded, but none of its requirements (F-042-5, F-042-6, N-042-1) changed",
                      "\n".join(c["details"]))
        # Changing the requirement the AC serves is the legitimate path.
        self.p.write(spec, self.p.read(spec).replace('is shown as "Unknown" instead of failing the page.',
                                                     'is shown as "Unknown".'))
        self.assertEqual(self.gate("ci", "immutable", ticket=None)["immutable"]["status"], "pass")

    def test_deleting_an_accepted_ticket(self) -> None:
        (self.p.root / "tickets" / "T-042-01-returns-api.md").unlink()
        c = self.gate("ci", "immutable", ticket=None)["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("tickets/T-042-01-returns-api.md: done ticket deleted", "\n".join(c["details"]))

    def test_full_build_gate_passes_on_the_reference_solution(self) -> None:
        self.apply_solution()
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(self.code, 0, self.out)


if __name__ == "__main__":
    unittest.main()
