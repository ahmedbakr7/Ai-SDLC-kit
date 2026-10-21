"""Each check must catch the failure it exists for. These are the defects that shipped
in a real product built without them (routes mounted at the wrong prefix, tests that
read source text, "green" suites that ran nothing, AC with no test, edited ADRs)."""
import json
import re
import sys
import unittest
from pathlib import Path

from helpers import FIXTURES as FIXTURES_DIR, ProductRepo, git


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

    def test_table_in_code_but_not_in_contracts(self) -> None:
        self.p.write("app/schema.py", 'RETURNS = Table("returns")\nAUDIT = Table(\n    "audit_log",\n)\n')
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[tables]\npatterns = [\'\'\'Table\\(\\s*"(?P<name>\\w+)"\'\'\']\n'
                     'globs = ["app/**/*.py"]\n')
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail")
        self.assertEqual(c["details"], ["table in code but not in CONTRACTS: audit_log (app/schema.py:2)"])

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

    def test_sdlc_app_port_moves_smoke_off_a_busy_app_port(self) -> None:
        # Hangout pilot: two worktrees gating at once both took app.port; the override is per
        # machine, so neither edits the committed sdlc.toml.
        import socket
        from unittest import mock

        busy = socket.socket()  # the committed app.port, taken by the other worktree's gate
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[app]\n", f"[app]\nport = {taken}\n", 1))
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        try:
            c = self.gate("ci", "smoke", ticket=None)["smoke"]
            self.assertEqual(c["status"], "fail")
            self.assertIn(f"port {taken} (app.port) is already in use", c["summary"])
            with mock.patch.dict("os.environ", {"SDLC_APP_PORT": str(port)}):
                c = self.gate("ci", "smoke", ticket=None)["smoke"]
            # The app came up on the free port and answered probes (T-042-02's page is not built
            # yet, which smoke reports on its own).
            self.assertNotIn("already in use", c["summary"])
            self.assertIn("probe(s)", c["summary"], c)
        finally:
            busy.close()

    def test_sdlc_app_port_fills_the_port_placeholder(self) -> None:
        from unittest import mock

        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'lint = "python tools/lint.py"', 'lint = "python -c \\"import sys; sys.exit({port} != 4567)\\""', 1))
        self.assertEqual(self.gate("ci", "lint", ticket=None)["lint"]["status"], "fail")
        with mock.patch.dict("os.environ", {"SDLC_APP_PORT": "4567"}):
            self.assertEqual(self.gate("ci", "lint", ticket=None)["lint"]["status"], "pass", self.out)

    def test_doctor_shows_the_app_port_and_refuses_a_bad_override(self) -> None:
        from unittest import mock

        self.assertIn("app port 3123 (from app.port)", self.p.sdlc("doctor")[1])
        with mock.patch.dict("os.environ", {"SDLC_APP_PORT": "4567"}):
            self.assertIn("app port 4567 (from SDLC_APP_PORT)", self.p.sdlc("doctor")[1])
        for bad in ("0", "70000", "port", "\u00b2"):
            with mock.patch.dict("os.environ", {"SDLC_APP_PORT": bad}):
                code, out = self.p.sdlc("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn(f"ERROR SDLC_APP_PORT={bad!r}: must be a port number from 1 to 65535", out)

    def test_auto_port_gives_each_run_a_free_port_every_command_sees(self) -> None:
        # Parallel gates: no per-machine setting to pick, so two worktrees never share a port.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[app]\n", '[app]\nport = "auto"\n', 1).replace(
            'lint = "python tools/lint.py"',
            'lint = "python -c \\"import os, sys; sys.exit(not ({port} == int(os.environ[\'SDLC_APP_PORT\']) != 3123))\\""', 1))
        self.assertEqual(self.gate("ci", "lint", ticket=None)["lint"]["status"], "pass", self.out)
        c = self.gate("ci", "smoke", ticket=None)["smoke"]
        self.assertNotIn("already in use", c["summary"])
        self.assertIn("probe(s)", c["summary"], c)
        self.assertIn("(from app.port = auto)", self.p.sdlc("doctor")[1])
        from unittest import mock

        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('port = "auto"', "port = 3123", 1))
        with mock.patch.dict("os.environ", {"SDLC_APP_PORT": "auto"}):
            self.assertIn("(from SDLC_APP_PORT=auto)", self.p.sdlc("doctor")[1])
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("port = 3123", 'port = "any"', 1))
        code, out = self.p.sdlc("doctor")
        self.assertNotEqual(code, 0)
        self.assertIn("ERROR app.port = 'any': must be a port number from 1 to 65535, or \"auto\"", out)

    def hooks(self, setup: str, teardown: str = "import pathlib; pathlib.Path('.sdlc-run/made').unlink()") -> None:
        self.p.write("tools/setup.py", setup)
        self.p.write("tools/teardown.py", teardown)
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            "[app]\n", '[app]\nsetup = "python tools/setup.py"\nteardown = "python tools/teardown.py"\n', 1).replace(
            'lint = "python tools/lint.py"',
            'lint = "python -c \\"import os, sys; sys.exit(os.environ.get(\'DB_NAME\') != \'run_\' + os.environ[\'SDLC_RUN_ID\'])\\""', 1))

    MAKE = ("import os, pathlib; pathlib.Path('.sdlc-run/made').write_text('x')\n"
            "open(os.environ['SDLC_RUN_ENV'], 'a').write('# a comment\\nDB_NAME=run_' + os.environ['SDLC_RUN_ID'] + '\\n')\n")

    def test_setup_hands_its_resources_to_every_command_and_teardown_removes_them(self) -> None:
        self.hooks(self.MAKE)
        checks = self.gate("ci", "lint", ticket=None)
        self.assertEqual(checks["lint"]["status"], "pass", self.out)
        self.assertEqual((checks["setup"]["status"], checks["teardown"]["status"]), ("pass", "pass"), checks)
        self.assertIn("set DB_NAME", checks["setup"]["summary"])
        self.assertFalse((self.p.root / ".sdlc-run" / "made").exists())    # torn down
        self.assertEqual(list((self.p.root / ".sdlc-run").glob("run-env-*")), [])

    def test_a_failed_setup_fails_the_gate_skips_checks_and_still_tears_down(self) -> None:
        self.hooks("import pathlib, sys; pathlib.Path('.sdlc-run/made').write_text('x'); sys.exit(3)")
        checks = self.gate("ci", "lint", ticket=None)
        self.assertNotEqual(self.code, 0)
        self.assertEqual(checks["setup"]["status"], "fail")
        self.assertIn("app.setup exited 3", checks["setup"]["summary"])
        self.assertEqual((checks["lint"]["status"], checks["lint"]["summary"]), ("skip", "app.setup failed"))
        self.assertFalse((self.p.root / ".sdlc-run" / "made").exists())

    def test_setup_may_not_hand_over_the_kits_own_variables(self) -> None:
        self.hooks("import os, pathlib; pathlib.Path('.sdlc-run/made').write_text('x')\n"
                   "open(os.environ['SDLC_RUN_ENV'], 'a').write('SDLC_APP_PORT=1\\nPORT=2\\nnot a pair\\n')\n")
        c = self.gate("ci", "lint", ticket=None)["setup"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("$SDLC_RUN_ENV line 1: SDLC_APP_PORT is the kit's to set", c["details"])
        self.assertIn("$SDLC_RUN_ENV line 2: PORT is the kit's to set", c["details"])
        self.assertIn("$SDLC_RUN_ENV line 3: not KEY=VALUE: 'not a pair'", c["details"])

    def test_a_failed_teardown_fails_the_gate(self) -> None:
        self.hooks(self.MAKE, teardown="import sys; sys.exit(4)")
        checks = self.gate("ci", "lint", ticket=None)
        self.assertNotEqual(self.code, 0)
        self.assertEqual(checks["lint"]["status"], "pass")
        self.assertEqual(checks["teardown"]["status"], "fail")
        self.assertIn("app.teardown exited 4", checks["teardown"]["summary"])

    def test_a_teardown_without_a_setup_still_runs_and_commands_see_the_run_id(self) -> None:
        # Review of #54: teardown and SDLC_RUN_ID depended on a setup being configured.
        self.p.write(".sdlc-run/made", "x")
        self.p.write("tools/teardown.py", "import pathlib; pathlib.Path('.sdlc-run/made').unlink()")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            "[app]\n", '[app]\nteardown = "python tools/teardown.py"\n', 1).replace(
            'lint = "python tools/lint.py"', 'lint = "python -c \\"import os; os.environ[\'SDLC_RUN_ID\']\\""', 1))
        checks = self.gate("ci", "lint", ticket=None)
        self.assertEqual(checks["lint"]["status"], "pass", self.out)
        self.assertEqual(checks["teardown"]["status"], "pass", checks)
        self.assertFalse((self.p.root / ".sdlc-run" / "made").exists())

    def test_setup_may_set_ci_and_no_color_without_crashing_the_gate(self) -> None:
        # Review of #54: a duplicate keyword built the command env and crashed the gate.
        self.hooks("import os, pathlib; pathlib.Path('.sdlc-run/made').write_text('x')\n"
                   "open(os.environ['SDLC_RUN_ENV'], 'a').write('CI=yes\\nNO_COLOR=0\\nDB_NAME=run_' + os.environ['SDLC_RUN_ID'] + '\\n')\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            "sys.exit(os.environ.get('DB_NAME') != 'run_' + os.environ['SDLC_RUN_ID'])",
            "sys.exit(os.environ.get('CI') != 'yes')", 1))
        checks = self.gate("ci", "lint", ticket=None)
        self.assertEqual(checks["lint"]["status"], "pass", self.out)

    def test_a_setup_env_that_is_not_utf8_fails_setup_and_still_tears_down(self) -> None:
        # Review of #54: the decode error escaped before the try, so teardown never ran and the
        # env file (which may hold credentials) stayed behind.
        self.hooks("import os, pathlib; pathlib.Path('.sdlc-run/made').write_text('x')\n"
                   "open(os.environ['SDLC_RUN_ENV'], 'wb').write(b'DB=\\xff\\n')\n")
        checks = self.gate("ci", "lint", ticket=None)
        self.assertEqual(checks["setup"]["status"], "fail")
        self.assertIn("not UTF-8", checks["setup"]["summary"])
        self.assertEqual(checks["teardown"]["status"], "pass")
        self.assertFalse((self.p.root / ".sdlc-run" / "made").exists())
        self.assertEqual(list((self.p.root / ".sdlc-run").glob("run-env-*")), [])

    def test_client_calls_a_path_no_contract_serves(self) -> None:
        self.p.write("app/static/app.js", 'export const load = (id) => fetch(`/v1/orders/${id}/returns`);\n')
        with open(self.p.root / "sdlc.toml", "a", encoding="utf-8") as f:
            f.write('\n[client]\npatterns = [\'\'\'fetch\\(\\s*[`"\'](?P<path>/[^`"\'\\s?#]*)\'\'\']\n'
                    'globs = ["app/static/**"]\nprefix = "/"\n')
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("client calls /v1/orders/{}/returns at app/static/app.js:1", "\n".join(c["details"]))

    def test_client_calls_a_contract_path_no_built_route_serves(self) -> None:
        # Hangout pilot: the UI fetched /v1/... as CONTRACTS said, but the handlers were served
        # at /api/v1/...; the client check compared UI calls with CONTRACTS only, so it was silent.
        self.p.write("app/static/app.js", 'export const load = (id) => fetch(`/api/orders/${id}/returns`);\n')
        with open(self.p.root / "sdlc.toml", "a", encoding="utf-8") as f:
            f.write('\n[client]\npatterns = [\'\'\'fetch\\(\\s*[`"\'](?P<path>/[^`"\'\\s?#]*)\'\'\']\n'
                    'globs = ["app/static/**"]\nprefix = "/"\n')
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertEqual(c["status"], "pass", c)  # declared and built: the call is served
        self.p.write("app/server.py", self.p.read("app/server.py").replace(
            '"/api/orders/{id}/returns"', '"/api/v1/orders/{id}/returns"'))
        c = self.gate("ci", "contracts", ticket=None)["contracts"]
        self.assertIn("client calls /api/orders/{}/returns at app/static/app.js:1; CONTRACTS declares it, "
                      "but no built route serves it", c["details"])

    def test_smoke_fails_when_a_contract_page_is_not_served(self) -> None:
        # T-042-02 is in progress, so its page must answer; the page is not built yet.
        c = self.gate("build", "smoke")["smoke"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("page /orders/{id}", "\n".join(c["details"]))

    def test_smoke_fails_when_no_built_route_is_at_a_contract_path(self) -> None:
        # Hangout pilot: CONTRACTS said /v1/..., the app served /api/v1/... and declared no
        # pages, so smoke probed nothing and passed ("0 route/page probe(s) answered").
        self.p.write("app/server.py", self.p.read("app/server.py").replace(
            '"/api/orders/{id}/returns"', '"/api/v1/orders/{id}/returns"'))
        c = self.gate("ci", "smoke", ticket=None)["smoke"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("the app serves 1 route(s), none at a CONTRACTS path, so no route was probed",
                      c["details"])

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

    def test_tautology_beside_the_module_the_ticket_creates(self) -> None:
        # The natural place for it: the test file that imports the new app/pages.py. Deleting
        # pages.py failed that whole file at import, so the tautology counted as red.
        self.apply_solution()
        t = self.p.read("app/test_pages.py")
        i = t.index('"""T-042-02/AC-3"""')
        self.p.write("app/test_pages.py", t[:i] + '"""T-042-02/AC-3"""\n        self.assertTrue(True)\n')
        pages = (self.p.root / "app" / "pages.py").read_bytes()
        c = self.gate("build", "unit", "ac-red")["ac-red"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(len(c["details"]), 1, c["details"])
        self.assertIn("T-042-02/AC-3: passes without this ticket's code", c["details"][0])
        self.assertEqual((self.p.root / "app" / "pages.py").read_bytes(), pages)

    def test_any_gate_restores_what_an_interrupted_ac_red_reverted(self) -> None:
        self.apply_solution()
        pages = self.p.read("app/pages.py")
        backup = self.p.root / ".sdlc-run" / "red-backup"
        backup.mkdir(parents=True)
        (backup / "0").write_text(pages, encoding="utf-8")
        (backup / "manifest.json").write_text(json.dumps({"app/pages.py": "0"}), encoding="utf-8")
        self.p.write("app/pages.py", "# reverted by a killed ac-red\n")
        self.gate("build", "lint")
        self.assertEqual(self.p.read("app/pages.py"), pages)
        self.assertFalse(backup.exists())

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

    def test_inverted_and_conditionally_skipped_tests(self) -> None:
        # Vitest's it.fails and unittest's expectedFailure report "passed" when the assertion
        # fails: tagged with an AC they prove the opposite of the AC.
        self.apply_solution()
        self.p.write("app/test_pages.py", self.p.read("app/test_pages.py").replace(
            "    def test_no_returns_no_heading", "    @unittest.expectedFailure\n    def test_no_returns_no_heading"))
        self.p.write("tests/ui.test.ts", "it.fails('T-042-02/AC-1 shows status', () => {})\n"
                     "describe.concurrent.only('focused', () => {})\n"
                     "it.skipIf(process.env.CI)('flaky', () => {})\n")
        c = self.gate("build", "test-quality")["test-quality"]
        self.assertEqual(c["status"], "fail")
        details = c["details"]
        self.assertTrue(any(d.startswith("app/test_pages.py:") and "expected-failure" in d for d in details), details)
        for ln, msg in ((1, "expected-failure"), (2, "focused"), (3, "conditionally skipped")):
            self.assertTrue(any(d.startswith(f"tests/ui.test.ts:{ln}: ") and msg in d for d in details), details)

    def test_file_outside_ticket_areas_is_flagged_not_failed(self) -> None:
        # ADR-0001: areas are soft. The builder does not stop; the reviewer must accept the file.
        self.apply_solution()
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# drive-by edit\n")
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)
        self.assertIn("out of area (the approving review must name it under ## Out of area): app/returns.py",
                      c["details"])
        self.assertIn("1 out of the ticket's areas (flagged for review)", c["summary"])

    def test_lead_artifacts_stay_outside_every_ticket(self) -> None:
        self.apply_solution()
        for rel in ("arch/plan-042-return-status.md", "tickets/T-042-01-returns-api.md",
                    "evidence/T-042-01.build.json", "reviews/T-042-01.md"):
            with self.subTest(rel=rel):
                self.p.write(rel, self.p.read(rel) + "\n")
                c = self.gate("build", "scope")["scope"]
                self.assertEqual(c["status"], "fail", c)
                self.assertIn(f"outside build write set: {rel}", c["details"])
                from helpers import git
                git(self.p.root, "checkout", "-q", "--", rel)

    def test_review_must_name_each_out_of_area_file(self) -> None:
        from helpers import git

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.apply_solution()
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# shared helper touched by the build\n")
        self.p.commit("build T-042-02")
        code, out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_review", "--as", "build")[0], 0)
        self.p.commit("evidence T-042-02: build gate pass")
        proven = self.run_test_play()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        review = review.replace("{commit}", proven)
        self.p.write("reviews/T-042-02.md", review)
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("out of area and not named under ## Out of area in reviews/T-042-02.md: app/returns.py",
                      c["details"])
        self.p.write("reviews/T-042-02.md", review + "\n## Out of area\n\n- `app/returns.py`: comment only\n")
        self.assertEqual(self.gate("review", "review-file")["review-file"]["status"], "pass")

    def test_agent_cannot_reconfigure_its_own_gate(self) -> None:
        # The agent drops `scope` from the build gate so its stray file goes unnoticed.
        self.apply_solution()
        self.p.write("app/stray.py", "x = 1\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\nbuild = ["artifacts", "unit"]\n')
        checks = self.gate("build", "scope", "unit")  # KeyError if the branch's plan was obeyed
        self.assertEqual(checks["scope"]["status"], "fail")
        details = "\n".join(checks["scope"]["details"])
        self.assertIn("out of area (the approving review must name it under ## Out of area): app/stray.py", details)
        self.assertIn("outside build write set: sdlc.toml", details)
        self.assertIn("differs from main", details)

    def sneaky_branch(self) -> None:
        """A PR that moves no ticket: adds a route CONTRACTS does not declare and trims the CI gate."""
        from helpers import git

        git(self.p.root, "checkout", "-q", "-b", "sneaky")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\nci = ["artifacts"]\n')
        self.p.write("app/server.py", self.p.read("app/server.py").replace(
            '("api", "GET", "/api/orders/{id}/returns", get_returns),',
            '("api", "GET", "/api/orders/{id}/returns", get_returns),\n    ("api", "DELETE", "/api/orders/{id}", get_returns),'))
        self.p.commit("sneaky")

    def test_ci_is_judged_by_the_base_branch_config(self) -> None:
        self.sneaky_branch()
        checks = self.gate("ci", "artifacts", "contracts", ticket=None)  # KeyError if the PR's plan was obeyed
        self.assertEqual(checks["contracts"]["status"], "fail")
        self.assertIn("differs from main", self.out)
        self.assertIn("admin override", self.out)  # the way out when the base config itself is broken
        # A base CI cannot resolve (shallow clone) must not fall back to trusting the PR's config.
        code, out = self.p.sdlc("gate", "ci", "--base", "origin/nowhere", "--only", "artifacts")
        self.assertNotEqual(code, 0, out)
        self.assertIn("fetch-depth: 0", out)

    def test_pr_that_moves_no_ticket_reports_code_and_fails_it_when_configured(self) -> None:
        # CI used to gate only tickets whose file the PR touched: this PR had no ticket gate at all.
        self.lead_config("[app]", '[scope]\nlead_code = "fail"\n\n[app]')
        self.sneaky_branch()
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main", "-v")
        self.assertNotEqual(self.code, 0, self.out)
        self.assertIn("no ticket moves on this branch", self.out)
        self.assertIn("outside the lead write set: app/server.py", self.out)
        self.assertNotIn("outside the lead write set: sdlc.toml", self.out)  # config is the lead's

    def test_pr_that_moves_no_ticket_warns_about_code_by_default(self) -> None:
        # A human hotfix passes, but the PR gate names every file no ticket traces.
        self.sneaky_branch()
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertEqual(self.code, 0, self.out)
        self.assertIn("WARNING 1 file(s) changed without a ticket, so no ticket traces them: app/server.py", self.out)

    def test_migrate_pr_moves_no_ticket(self) -> None:
        # Hangout pilot: `sdlc migrate` (MIGRATION.md step 2) numbers the AC of every done
        # ticket, and gate pr read that branch as moving 30 tickets, so it could never pass.
        import re

        from helpers import git

        rel = "tickets/T-042-01-returns-api.md"
        self.p.write(rel, re.sub(r'"AC-\d+: ', '"', self.p.read(rel)))
        self.p.commit("a v0 ticket: AC not numbered")
        git(self.p.root, "checkout", "-q", "-b", "lead/migrate")
        code, out = self.p.sdlc("migrate")
        self.assertEqual(code, 0, out)
        self.p.commit("sdlc migrate")
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertIn("gate pr: no ticket moves on this branch; judging it as a lead PR", self.out)
        self.assertEqual(self.code, 0, self.out)
        # Anything beyond the numbering is a real edit of a done ticket.
        self.p.write(rel, self.p.read(rel).replace("empty returns list", "empty list"))
        self.p.commit("reword an AC")
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertIn("gate pr: ticket T-042-01", self.out)

    def test_migrate_pr_that_marks_legacy_moves_no_ticket(self) -> None:
        # The v0 ticket shipped without a v1 review: migrate numbers its AC and marks it legacy.
        import re

        from helpers import git

        rel = "tickets/T-042-01-returns-api.md"
        self.p.write(rel, re.sub(r'"AC-\d+: ', '"', self.p.read(rel)))
        (self.p.root / "reviews" / "T-042-01.md").unlink()
        self.p.commit("a v0 ticket shipped without a v1 review")
        git(self.p.root, "checkout", "-q", "-b", "lead/migrate")
        code, out = self.p.sdlc("migrate")
        self.assertIn("marked legacy: v0", out)
        self.p.commit("sdlc migrate")
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertIn("gate pr: no ticket moves on this branch; judging it as a lead PR", self.out)
        self.assertEqual(self.code, 0, self.out)

    def test_lead_pr_with_only_lead_artifacts_passes(self) -> None:
        from helpers import git

        git(self.p.root, "checkout", "-q", "-b", "lead/plan")
        self.p.write("arch/CONTRACTS.md", self.p.read("arch/CONTRACTS.md") + "\n<!-- clarified -->\n")
        self.p.write("design/spec-042-return-status.md",
                     self.p.read("design/spec-042-return-status.md") + "\nA note from the lead.\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[app]", "[app]\nready_timeout = 90"))
        self.p.commit("lead: plan")
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertEqual(self.code, 0, self.out)
        self.assertIn("lead PR: 3 changed file(s), all lead artifacts", self.out)

    def test_pr_finds_the_ticket_it_moves(self) -> None:
        self.build_and_commit()
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertIn("gate pr: ticket T-042-02", self.out)
        self.assertNotIn("moves 2 tickets", self.out)
        # A second ticket's file on the same branch: one PR, one ticket.
        t = self.p.read("tickets/T-042-01-returns-api.md")
        self.p.write("tickets/T-042-01-returns-api.md", t.replace("status: done", "status: in_review"))
        self.p.commit("drag another ticket along")
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertNotEqual(self.code, 0)
        self.assertIn("moves 2 tickets (T-042-01, T-042-02)", self.out)

    def test_pr_needs_a_reviewed_done_ticket(self) -> None:
        # Hangout: review ran on the open PR, so a PR sat waiting on review threads. Review now
        # happens before the PR, and the PR gate refuses a ticket that is not done.
        self.build_and_commit()
        self.code, self.out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertNotEqual(self.code, 0, self.out)
        self.assertIn("T-042-02 is in_review: open the PR after review (an approving reviews/T-042-02.md, "
                      "then `sdlc status T-042-02 done --as merge`)", self.out)

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

    def run_test_play(self) -> str:
        """The reference test play on top of build_and_commit(). Returns the commit it proved."""
        self.apply_solution("test-T-042-02")
        self.p.commit("test T-042-02")
        code, out = self.p.sdlc("gate", "test", "T-042-02")
        self.assertEqual(code, 0, out)
        self.p.commit("evidence T-042-02: test gate pass")
        return json.loads(self.p.read("evidence/T-042-02.test.json"))["commit"]

    def test_approval_needs_the_test_play_when_the_product_has_integration_tests(self) -> None:
        # build -> review -> done skipped the only proof through the real stack.
        build = self.build_and_commit()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        self.p.write("reviews/T-042-02.md", review.replace("{commit}", build))
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("no test evidence evidence/T-042-02.test.json", "\n".join(c["details"]))
        # The agent cannot opt out by dropping the integration command on its branch.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""'))
        self.assertEqual(self.gate("review", "review-file")["review-file"]["status"], "fail")

    def test_approval_without_a_test_play_only_when_the_lead_accepts_unit_proof(self) -> None:
        # No real-stack suite is not a free pass: the lead must say so (tests.real_stack = []).
        self.lead_config('integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""')
        build = self.build_and_commit()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        self.p.write("reviews/T-042-02.md", review.replace("{commit}", build))
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no real-stack suite is configured (tests.real_stack: integration, e2e)", "\n".join(c["details"]))

    def test_approval_without_a_test_play_when_the_lead_sets_real_stack_empty(self) -> None:
        self.lead_config('integration = "python tools/junit.py --start tests --out {junit}"', 'integration = ""')
        self.lead_config("[tests]\n", "[tests]\nreal_stack = []\n")
        build = self.build_and_commit()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        self.p.write("reviews/T-042-02.md", review.replace("{commit}", build))
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "pass", c)

    def test_only_the_suites_in_real_stack_prove_the_test_play(self) -> None:
        # Hangout pilot: vitest "integration" tests called route handlers in-process under
        # jsdom, never over HTTP, yet counted as real-stack proof. The nextjs profile names e2e.
        self.lead_config("[tests]\n", '[tests]\nreal_stack = ["e2e"]\n')
        self.build_and_commit()
        self.apply_solution("test-T-042-02")
        self.p.commit("test T-042-02")
        c = self.gate("test", "unit", "integration", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no passing e2e test carries a T-042-02/AC-n tag", c["summary"])

    def test_lead_may_mark_a_ticket_test_none(self) -> None:
        ticket = "tickets/T-042-02-order-page.md"
        text = self.p.read(ticket)
        # Not on a ticket that serves a page: that is where unit tests on stubs lie.
        self.p.write(ticket, text.replace("risk: low", "risk: low\ntest: none"))
        c = self.gate("ci", "artifacts", ticket=None)["artifacts"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("test: none, but the ticket implements /orders/{id}", "\n".join(c["details"]))
        self.p.write(ticket, text.replace("risk: low", "risk: low\ntest: sometimes"))
        self.assertIn("test must be required or none", "\n".join(self.gate("ci", "artifacts", ticket=None)["artifacts"]["details"]))
        # On a ticket that serves nothing over HTTP, the lead's `test: none` lets review approve the build.
        self.p.write(ticket, text.replace("risk: low", "risk: low\ntest: none")
                     .replace("contracts:\n  - /orders/{id}", "contracts: []"))
        self.p.commit("lead: T-042-02 needs no test play")
        build = self.build_and_commit()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        self.p.write("reviews/T-042-02.md", review.replace("{commit}", build))
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "pass", c)

    def test_build_agent_cannot_opt_its_ticket_out_of_the_test_play(self) -> None:
        self.apply_solution()
        ticket = "tickets/T-042-02-order-page.md"
        self.p.write(ticket, self.p.read(ticket).replace("risk: low", "risk: low\ntest: none"))
        c = self.gate("build", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn(f"{ticket}: test changed; a ticket PR may amend acceptance criteria, areas, transforms, "
                      "skills, contracts (add only) and raise lane or risk; test is the lead's", c["details"])

    def test_review_must_name_the_proven_commit_exactly(self) -> None:
        self.build_and_commit()
        proven = self.run_test_play()
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

    def test_widening_and_amendments_still_need_the_reviewer(self) -> None:
        # Review of step 1: a `widen` line dodged the Out of area acknowledgement, and a
        # `strengthen` line let a weaker AC through with nobody required to judge it.
        from helpers import git

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.apply_solution()
        rel = "tickets/T-042-02-order-page.md"
        ac3 = "and the page still answers 200"
        t = self.p.read(rel).replace("  - app/server.py\n", "  - app/server.py\n  - app/returns.py\n")
        t = t.replace(ac3, ac3 + " with a plain heading")
        self.p.write(rel, t.rstrip("\n") + "\n\n## Amendments\n\n- widen app/returns.py: shared helper\n"
                     "- strengthen AC-3: also checks the heading\n")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# shared helper touched by the build\n")
        self.p.commit("build T-042-02")
        code, out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_review", "--as", "build")[0], 0)
        self.p.commit("evidence T-042-02: build gate pass")
        proven = self.run_test_play()
        review = (FIXTURES_DIR / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
        review = review.replace("{commit}", proven)
        self.p.write("reviews/T-042-02.md", review + "\n## Out of area\n\n- `**` everything is fine\n"
                     "- `**/?*` and this too\n- `*.py` and this\n")
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "fail", c)
        details = "\n".join(c["details"])
        self.assertIn("out of area and not named under ## Out of area in reviews/T-042-02.md: app/returns.py", details)
        self.assertIn("amendment `widen app/returns.py` is not named under ## Amendments", details)
        self.assertIn("amendment `strengthen AC-3` is not named under ## Amendments", details)
        self.p.write("reviews/T-042-02.md", review + "\n## Out of area\n\n- `app/returns.py`: comment only\n"
                     "\n## Amendments\n\n- `app/returns.py`: fine\n- `AC-3`: stronger, it adds a check\n")
        c = self.gate("review", "review-file")["review-file"]
        self.assertEqual(c["status"], "pass", c)

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
        c = self.gate("ci", "unit", "integration", "ac-coverage", ticket=None)["ac-coverage"]
        self.assertEqual(c["status"], "pass", c)
        self.assertIn("all 4 AC of 1 ticket(s)", c["summary"])
        self.p.write("app/test_returns.py", self.p.read("app/test_returns.py").replace('"""T-042-01/AC-4"""', '"""404"""'))
        self.p.write("tests/test_http_returns.py", self.p.read("tests/test_http_returns.py").replace(
            '"""T-042-01/AC-4"""', '"""404 over http"""'))
        c = self.gate("ci", "unit", "integration", "ac-coverage", ticket=None)["ac-coverage"]
        self.assertEqual(c["status"], "fail")
        self.assertEqual(c["details"], ["T-042-01/AC-4: missing"])

    def test_ci_reproves_the_real_stack_proof_test_evidence_claims(self) -> None:
        # evidence/<id>.test.json is a file the ticket PR writes; a hand-written "pass" let a
        # done ticket ship with unit tests only. CI re-runs integration and checks the tags.
        self.p.write("tests/test_http_returns.py", self.p.read("tests/test_http_returns.py")
                     .replace('"""T-042-01/AC-1"""', '"""mounted"""').replace('"""T-042-01/AC-4"""', '"""404"""'))
        c = self.gate("ci", "unit", "integration", "ac-coverage", ticket=None)["ac-coverage"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("T-042-01: done, but no passing integration/e2e test carries its tag", c["details"])

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

    def test_commands_run_in_a_root_with_spaces(self) -> None:
        # An absolute {junit} path split at the space: unit failed on any such checkout.
        from helpers import ProductRepo

        p = ProductRepo("my product")
        try:
            code, out = p.sdlc("gate", "ci", "--only", "unit")
            self.assertEqual(code, 0, out)
            self.assertIn("--out .sdlc-run/junit-unit.xml", p.read(".sdlc-run/logs/unit.log").splitlines()[0])
        finally:
            p.close()

    def test_full_build_gate_passes_on_the_reference_solution(self) -> None:
        self.apply_solution()
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(self.code, 0, self.out)



class TestTickets(unittest.TestCase):
    """Pilot finding 19: a ticket that changes tests only, with an AC only an integration test
    can prove, could not pass `gate build` (unit alone; integration files refused)."""

    TICKET = """---
id: T-042-03
title: Returns route answers an unknown order over HTTP
type: test
status: in_progress
risk: low
depends_on: [T-042-01]
files:
  - tests/test_http_unknown.py
skills:
  - build
contracts: []
requirements:
  - F-042-4
acceptance_criteria:
  - "AC-1: an integration test proves GET /api/orders/nope/returns answers 404 over HTTP"
source_intent: intent/intent-042-return-status.md
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
---

Add the HTTP test.
"""
    TEST = (
        '"""Integration: an unknown order over HTTP."""\n'
        "import threading\nimport unittest\nimport urllib.error\nimport urllib.request\n\n"
        "from app.server import Handler, Server\n\n\n"
        "class UnknownOrder(unittest.TestCase):\n"
        "    def test_unknown_order(self) -> None:\n"
        '        """T-042-03/AC-1"""\n'
        '        server = Server(("127.0.0.1", 0), Handler)\n'
        "        threading.Thread(target=server.serve_forever, daemon=True).start()\n"
        "        try:\n"
        "            with self.assertRaises(urllib.error.HTTPError) as e:\n"
        '                urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/orders/nope/returns")\n'
        "            self.assertEqual(e.exception.code, 404)\n"
        "        finally:\n"
        "            server.shutdown()\n")

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write("tickets/T-042-03-unknown-order-http.md", self.TICKET)
        self.p.commit("lead: test ticket T-042-03")
        from helpers import git

        self.git = git

    def tearDown(self) -> None:
        self.p.close()

    def checks(self, ticket: str, *only: str) -> dict:
        self.code, self.out = self.p.sdlc("gate", "build", ticket, "--only", ",".join(only))
        ev = json.loads((self.p.root / ".sdlc-run" / f"{ticket}.build.json").read_text(encoding="utf-8"))
        return {c["name"]: c for c in ev["checks"]}

    def test_a_test_ticket_builds_with_an_integration_test_alone(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        c = self.checks("T-042-03", "scope", "unit", "integration", "ac-coverage")
        self.assertEqual(list(c), ["scope", "unit", "integration", "ac-coverage"])
        self.assertEqual(c["scope"]["status"], "pass", c["scope"])
        self.assertEqual(c["integration"]["status"], "pass", c["integration"])
        self.assertEqual(c["ac-coverage"]["status"], "pass", c["ac-coverage"])

    def test_a_test_ticket_needs_a_tagged_real_stack_test_not_just_a_unit_one(self) -> None:
        # Its build skips the test play, so a unit test with the tag plus some unrelated passing
        # integration test must not count as real-stack proof.
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("app/test_unknown.py", "import unittest\n\n\nclass U(unittest.TestCase):\n"
                     "    def test_unknown(self) -> None:\n        \"\"\"T-042-03/AC-1\"\"\"\n        self.assertTrue(True)\n")
        self.p.write("tests/test_http_unknown.py", self.TEST.replace("T-042-03/AC-1", "no tag"))
        c = self.checks("T-042-03", "unit", "integration", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no passing integration/e2e test carries a T-042-03/AC-n tag; the test ticket's build", c["summary"])

    def test_a_test_ticket_runs_its_real_stack_suite_before_coverage_whatever_the_order(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\nbuild = ["scope", "unit", "ac-coverage", "integration"]\n')
        self.p.commit("lead: integration listed after coverage")
        from sdlc import config
        from sdlc.gate import Gate

        names = Gate(config.load(self.p.root), "build", "T-042-03", "main").plan()
        self.assertLess(names.index("integration"), names.index("ac-coverage"), names)
        self.assertEqual(names.count("integration"), 1)

    def test_approval_refuses_a_test_tickets_build_without_recorded_real_stack_proof(self) -> None:
        # A build recorded before v2.0.0 ran unit (and maybe some integration suite) with no tagged
        # real-stack proof; the test ticket has no test play to fill in.
        from sdlc import config
        from sdlc.artifacts import Repo
        from sdlc.gate import _evidence_problems

        cfg = config.load(self.p.root)
        t = Repo(cfg).ticket("T-042-03")
        ev = {"result": "pass", "dirty": False, "commit": "a" * 40,
              "checks": [{"name": "unit", "status": "pass"}, {"name": "integration", "status": "pass"},
                         {"name": "ac-coverage", "status": "pass"}]}
        self.p.write("evidence/T-042-03.build.json", json.dumps(ev))
        problems = _evidence_problems(cfg, t, "a" * 40)
        self.assertIn("build evidence for test ticket T-042-03 records no passing real-stack test with one of its "
                      "AC tags (integration); re-run the build", problems)
        # A test play that passed before the upgrade (v1.5.5 gave test tickets one) still proves it.
        self.p.write("evidence/T-042-03.test.json", json.dumps({**ev, "play": "test"}))
        self.assertFalse([x for x in _evidence_problems(cfg, t, "a" * 40) if "real-stack" in x])
        (self.p.root / "evidence" / "T-042-03.test.json").unlink()
        ev["real_stack_proof"] = True
        self.p.write("evidence/T-042-03.build.json", json.dumps(ev))
        problems = _evidence_problems(cfg, t, "a" * 40)
        self.assertFalse([x for x in problems if "real-stack" in x])
        self.assertFalse([x for x in problems if x.startswith("no test evidence")], problems)  # it has no test play

    def test_approval_asks_no_test_play_of_a_ticket_without_ac(self) -> None:
        # A ticket with no AC has no tag a real-stack test could carry (Hangout pilot, T-001-69).
        from sdlc import config
        from sdlc.artifacts import Repo
        from sdlc.gate import _evidence_problems

        rel = "tickets/T-042-02-order-page.md"
        text = self.p.read(rel)
        self.p.write(rel, text[:text.index("acceptance_criteria:\n")] + "acceptance_criteria: []\n"
                     + text[text.index("source_intent:"):])
        ev = {"result": "pass", "dirty": False, "commit": "a" * 40, "checks": []}
        self.p.write("evidence/T-042-02.build.json", json.dumps(ev))
        cfg = config.load(self.p.root)
        problems = _evidence_problems(cfg, Repo(cfg).ticket("T-042-02"), "a" * 40)
        self.assertFalse([x for x in problems if x.startswith("no test evidence")], problems)
        self.p.write(rel, text)  # with its AC back, the test play is owed again
        problems = _evidence_problems(config.load(self.p.root), Repo(config.load(self.p.root)).ticket("T-042-02"),
                                      "a" * 40)
        self.assertTrue([x for x in problems if x.startswith("no test evidence")], problems)

    def test_approval_refuses_a_test_ticket_when_no_real_stack_suite_has_a_command(self) -> None:
        # As for any other ticket, only tests.real_stack = [] accepts unit-only proof.
        from sdlc import config
        from sdlc.artifacts import Repo
        from sdlc.gate import _evidence_problems

        self.p.write("sdlc.toml", re.sub(r'(?m)^integration = .*$', 'integration = ""', self.p.read("sdlc.toml")))
        self.p.commit("lead: no integration command")
        cfg = config.load(self.p.root)
        t = Repo(cfg).ticket("T-042-03")
        ev = {"result": "pass", "dirty": False, "commit": "a" * 40, "checks": [{"name": "unit", "status": "pass"}]}
        self.p.write("evidence/T-042-03.build.json", json.dumps(ev))
        problems = _evidence_problems(cfg, t, "a" * 40)
        self.assertTrue([x for x in problems if x.startswith("no real-stack suite is configured")], problems)
        self.assertFalse([x for x in problems if x.startswith("no test evidence")], problems)

    def test_a_test_tickets_build_records_its_real_stack_proof(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        self.checks("T-042-03", "unit", "integration", "ac-coverage")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-03.build.json").read_text(encoding="utf-8"))
        self.assertIs(ev["real_stack_proof"], True)

    def test_real_stack_proof_needs_a_tag_the_ticket_declares(self) -> None:
        # A tagged unit test proves AC-1; an integration test tagged AC-9, an AC the ticket does
        # not have, proves none of its AC through the real stack.
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("app/test_unknown.py", "import unittest\n\n\nclass U(unittest.TestCase):\n"
                     "    def test_unknown(self) -> None:\n        \"\"\"T-042-03/AC-1\"\"\"\n        self.assertTrue(True)\n")
        self.p.write("tests/test_http_unknown.py", self.TEST.replace("T-042-03/AC-1", "T-042-03/AC-9"))
        c = self.checks("T-042-03", "unit", "integration", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no passing integration/e2e test carries a T-042-03/AC-n tag", c["summary"])

    def test_an_undeclared_tag_that_extends_a_declared_one_proves_nothing(self) -> None:
        # With two AC, AC-27 must not match through the AC-2 alternative of the tag pattern.
        self.p.write("tickets/T-042-03-unknown-order-http.md", self.TICKET.replace(
            '  - "AC-1:', '  - "AC-2: the 404 body names the order"\n  - "AC-1:'))
        self.p.commit("lead: a second AC")
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("app/test_unknown.py", "import unittest\n\n\nclass U(unittest.TestCase):\n"
                     "    def test_unknown(self) -> None:\n        \"\"\"T-042-03/AC-1 T-042-03/AC-2\"\"\"\n"
                     "        self.assertTrue(True)\n")
        self.p.write("tests/test_http_unknown.py", self.TEST.replace("T-042-03/AC-1", "T-042-03/AC-27"))
        c = self.checks("T-042-03", "unit", "integration", "ac-coverage")["ac-coverage"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no passing integration/e2e test carries a T-042-03/AC-n tag", c["summary"])

    def test_a_test_ticket_may_not_change_production_code(self) -> None:
        # It skips the test play, so declaring type: test must not carry code past real-stack proof.
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\nEXTRA = 1\n")
        c = self.checks("T-042-03", "scope")["scope"]
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["details"], ["a test ticket changes tests only (tests.globs, tests.integration_globs): app/returns.py"])

    def test_a_test_ticket_may_split_an_ac_into_a_new_draft_ticket(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        self.p.write("tickets/T-042-04-unknown-order-body.md",
                     self.TICKET.replace("id: T-042-03", "id: T-042-04\nsplit_from: T-042-03")
                     .replace("status: in_progress", "status: draft"))
        c = self.checks("T-042-03", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)

    def test_ci_re_proves_a_done_test_ticket_through_the_real_stack(self) -> None:
        self.p.write("tickets/T-042-03-unknown-order-http.md",
                     self.TICKET.replace("status: in_progress", "status: done"))
        self.p.commit("T-042-03 done, with no tagged real-stack test")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-03: done, but no passing", out)

    def test_a_test_ticket_may_write_integration_files_outside_the_test_globs(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('globs = ["app/test_*.py", "tests/**"]',
                                                                   'globs = ["app/test_*.py"]'))
        self.p.commit("lead: integration tests are not in tests.globs")
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        c = self.checks("T-042-03", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)

    def test_a_test_ticket_has_no_test_play_and_lints_clean(self) -> None:
        from sdlc import config
        from sdlc.artifacts import Repo
        from sdlc.lint import lint_repo

        repo = Repo(config.load(self.p.root))
        self.assertFalse(repo.ticket("T-042-03").test_play)
        self.assertTrue(repo.ticket("T-042-02").test_play)
        self.assertEqual([str(i) for i in lint_repo(repo) if "T-042-03" in str(i)], [])
        # It still owes real-stack proof (its build gives it), so a route it tests is no lint error.
        self.p.write("tickets/T-042-03-unknown-order-http.md",
                     self.TICKET.replace("contracts: []", "contracts:\n  - GET /api/orders/{id}/returns"))
        repo = Repo(config.load(self.p.root))
        self.assertEqual([str(i) for i in lint_repo(repo) if "routes and pages" in str(i)], [])

    def test_other_tickets_still_build_on_unit_alone_and_may_not_write_integration_tests(self) -> None:
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertEqual(code, 0, out)
        self.p.commit("start T-042-02")
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.p.write("tests/test_http_unknown.py", self.TEST)
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-02", "--only", "scope,integration")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        c = {x["name"]: x for x in ev["checks"]}
        self.assertNotIn("integration", c)
        self.assertEqual(c["scope"]["status"], "fail")
        self.assertIn("outside build write set: tests/test_http_unknown.py", c["scope"]["details"])


class DirtyTree(unittest.TestCase):
    """Evidence and `sdlc run` treat an untracked always_allowed file like an ignored one; every
    other uncommitted change still dirties the tree."""

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nalways_allowed = ["package-lock.json"]\n')
        self.p.commit("lead: lockfiles in scope")

    def tearDown(self) -> None:
        self.p.close()

    def dirty(self) -> bool:
        from sdlc import config, gate

        return gate.dirty_tree(config.load(self.p.root))

    def test_an_untracked_lockfile_leaves_the_tree_clean(self) -> None:
        self.assertFalse(self.dirty())
        self.p.write("package-lock.json", "{}\n")
        self.assertFalse(self.dirty())

    def test_a_change_to_a_tracked_lockfile_dirties_the_tree(self) -> None:
        self.p.write("package-lock.json", "{}\n")
        self.p.commit("lockfile committed")
        self.p.write("package-lock.json", '{"changed": true}\n')
        self.assertTrue(self.dirty())

    def test_any_other_untracked_file_dirties_the_tree(self) -> None:
        self.p.write("notes.txt", "x\n")
        self.assertTrue(self.dirty())

    def test_a_nested_product_excuses_only_its_own_lockfile(self) -> None:
        import tempfile
        from types import SimpleNamespace

        from helpers import git
        from sdlc import gate

        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp)
            git(top, "init", "-q", "-b", "main")
            git(top, "config", "user.email", "t@example.invalid")
            git(top, "config", "user.name", "t")
            (top / "sub").mkdir()
            (top / "sub" / "a.py").write_text("A = 1\n", encoding="utf-8")
            git(top, "add", "-A")
            git(top, "commit", "-qm", "start")
            cfg = SimpleNamespace(root=top / "sub",
                                  section=lambda name: {"always_allowed": ["package-lock.json"]})
            (top / "sub" / "package-lock.json").write_text("{}\n", encoding="utf-8")
            self.assertFalse(gate.dirty_tree(cfg))
            (top / "xyz").mkdir()  # a sibling product whose path is as long as this one's
            (top / "xyz" / "package-lock.json").write_text("{}\n", encoding="utf-8")
            self.assertTrue(gate.dirty_tree(cfg))

    def test_a_git_failure_fails_closed(self) -> None:
        import tempfile
        from types import SimpleNamespace

        from sdlc import config, gate, gitutil

        with tempfile.TemporaryDirectory() as tmp:
            cfg = SimpleNamespace(root=Path(tmp), section=lambda name: {"always_allowed": ["package-lock.json"]})
            with self.assertRaises(gitutil.GitError):
                gate.dirty_tree(cfg)
        # A repository git can find but not read (a corrupt index): status fails, not rev-parse.
        (self.p.root / ".git" / "index").write_bytes(b"garbage\n")
        with self.assertRaises(gitutil.GitError):
            gate.dirty_tree(config.load(self.p.root))

    def test_evidence_lists_the_untracked_allowed_files_the_run_could_read(self) -> None:
        self.p.write("package-lock.json", "{}\n")
        self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["untracked_allowed"], ["package-lock.json"])
        self.assertFalse(ev["dirty"])

    def test_evidence_does_not_list_a_file_head_holds(self) -> None:
        from helpers import git

        self.p.write("package-lock.json", "{}\n")
        self.p.commit("lockfile committed")
        git(self.p.root, "rm", "-q", "--cached", "package-lock.json")
        self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["untracked_allowed"], [])
        self.assertTrue(ev["dirty"])

    def test_the_runner_leaves_only_what_the_play_may_not_commit(self) -> None:
        from sdlc import config, run

        cfg = config.load(self.p.root)
        self.assertIsNone(run._leave(cfg, "build", "T-042-02", "main"))  # a build commits it
        self.assertTrue(run._leave(cfg, "test", "T-042-02", "main")("package-lock.json"))
        self.assertFalse(run._leave(cfg, "test", "T-042-02", "main")("app/returns.py"))
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'integration_globs = ["tests/**"]', 'integration_globs = ["tests/**", "package-lock.json"]', 1))
        self.p.commit("lead: the test play owns the lockfile")  # the gate reads the base's config
        self.assertFalse(run._leave(config.load(self.p.root), "test", "T-042-02", "main")("package-lock.json"))


def _check_rules() -> bool:
    """git 2.41+ answers which paths sparse-checkout patterns include; older git counts every
    off-disk skip-worktree file, so a test of the exemption needs it."""
    import subprocess

    r = subprocess.run(["git", "sparse-checkout", "check-rules", "-h"], capture_output=True, text=True)
    return "usage: git sparse-checkout check-rules" in r.stdout + r.stderr


class HiddenFiles(unittest.TestCase):
    """`git update-index --skip-worktree` / `--assume-unchanged` hide an edit from status, diff
    and `add -A`, so every other check missed it. Scope reports such files; it fails on them
    with scope.hidden_files = "fail"."""

    def setUp(self) -> None:
        from helpers import git

        self.git = git
        self.p = ProductRepo()
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertEqual(code, 0, out)
        self.p.commit("start T-042-02")

    def tearDown(self) -> None:
        self.p.close()

    def gate(self) -> tuple[dict, dict]:
        self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        return {x["name"]: x for x in ev["checks"]}["scope"], ev

    def hide(self, flag: str, f: str = "app/returns.py") -> None:
        self.git(self.p.root, "update-index", flag, f)
        self.p.write(f, self.p.read(f) + "\n# hidden edit\n")

    def test_a_skip_worktree_edit_is_reported_and_passes_by_default(self) -> None:
        self.hide("--skip-worktree")
        scope, ev = self.gate()
        self.assertEqual(scope["status"], "pass")
        self.assertIn("WARNING 1 tracked file(s) hidden from git", scope["summary"])
        self.assertIn("hidden from git (skip-worktree or assume-unchanged; changes to it are not checked): app/returns.py",
                      scope["details"])
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])

    def test_an_assume_unchanged_edit_is_reported(self) -> None:
        self.hide("--assume-unchanged")
        scope, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])
        self.assertIn("WARNING", scope["summary"])

    def test_fail_mode_fails_scope(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nhidden_files = "fail"\n')
        self.p.commit("lead: hidden files fail")
        self.hide("--skip-worktree")
        scope, _ = self.gate()
        self.assertEqual(scope["status"], "fail")
        self.assertIn("1 tracked file(s) hidden from git", scope["summary"])

    def fail_mode(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nhidden_files = "fail"\n')
        self.p.commit("lead: hidden files fail")

    @unittest.skipUnless(_check_rules(), "git sparse-checkout check-rules needs git 2.41+")
    def test_a_sparse_checkout_file_off_disk_does_not_count(self) -> None:
        self.fail_mode()
        self.git(self.p.root, "sparse-checkout", "set", "--no-cone", "/*", "!/app/returns.py")
        self.assertFalse((self.p.root / "app" / "returns.py").exists())
        scope, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], [])
        self.assertNotIn("hidden from git", scope["summary"])

    def test_a_deleted_skip_worktree_file_counts_without_sparse_checkout(self) -> None:
        self.fail_mode()
        self.git(self.p.root, "update-index", "--skip-worktree", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()  # status shows nothing: a failing test, gone
        scope, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])
        self.assertEqual(scope["status"], "fail")

    def test_a_deleted_file_inside_the_sparse_patterns_counts(self) -> None:
        self.fail_mode()
        self.git(self.p.root, "sparse-checkout", "set", "--no-cone", "/*")
        self.git(self.p.root, "update-index", "--skip-worktree", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()
        _, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])

    def test_turning_on_sparse_checkout_alone_exempts_nothing(self) -> None:
        self.fail_mode()
        self.git(self.p.root, "config", "core.sparseCheckout", "true")  # no patterns
        self.git(self.p.root, "update-index", "--skip-worktree", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()
        scope, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])
        self.assertEqual(scope["status"], "fail")

    def test_a_patterns_file_without_sparse_checkout_exempts_nothing(self) -> None:
        # check-rules reads info/sparse-checkout even when core.sparseCheckout is off.
        (self.p.root / ".git" / "info").mkdir(exist_ok=True)
        (self.p.root / ".git" / "info" / "sparse-checkout").write_text("/*\n!/app/returns.py\n", encoding="utf-8")
        self.git(self.p.root, "update-index", "--skip-worktree", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()
        _, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])

    def test_a_deleted_file_inside_a_cone_counts(self) -> None:
        dirs = self.git(self.p.root, "ls-tree", "-d", "--name-only", "HEAD").split()
        self.git(self.p.root, "sparse-checkout", "set", "--cone", *dirs)  # every directory in the cone
        self.git(self.p.root, "update-index", "--skip-worktree", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()
        _, ev = self.gate()
        self.assertIn("app/returns.py", ev["hidden_from_git"])

    def test_both_flags_on_a_file_outside_the_sparse_patterns_count(self) -> None:
        self.git(self.p.root, "sparse-checkout", "set", "--no-cone", "/*", "!/app/returns.py")
        self.git(self.p.root, "update-index", "--assume-unchanged", "app/returns.py")  # tag "s"
        _, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])

    def test_a_deleted_assume_unchanged_file_counts_even_with_sparse_checkout(self) -> None:
        self.fail_mode()
        self.git(self.p.root, "sparse-checkout", "set", "--no-cone", "/*")
        self.git(self.p.root, "update-index", "--assume-unchanged", "app/returns.py")
        (self.p.root / "app" / "returns.py").unlink()
        scope, ev = self.gate()
        self.assertEqual(ev["hidden_from_git"], ["app/returns.py"])
        self.assertEqual(scope["status"], "fail")

    def test_a_scope_failure_keeps_its_summary(self) -> None:
        self.hide("--skip-worktree")
        self.p.write("tickets/T-042-01-returns-api.md", self.p.read("tickets/T-042-01-returns-api.md") + "\n")
        scope, _ = self.gate()
        self.assertEqual(scope["status"], "fail")
        self.assertIn("outside the build play's write set", scope["summary"])
        self.assertNotIn("WARNING", scope["summary"])  # a warning never dresses up a failure
        self.fail_mode()
        self.p.write("tickets/T-042-01-returns-api.md", self.p.read("tickets/T-042-01-returns-api.md") + "\n")
        scope, _ = self.gate()
        self.assertIn("outside the build play's write set", scope["summary"])
        self.assertIn("1 tracked file(s) hidden from git", scope["summary"])

    def test_an_unknown_mode_fails(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nhidden_files = "off"\n')
        self.p.commit("lead: bad mode")
        scope, _ = self.gate()
        self.assertEqual(scope["status"], "fail")
        self.assertIn("scope.hidden_files must be warn or fail", scope["summary"])

    def test_an_unknown_mode_keeps_the_scope_summary(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nhidden_files = "off"\n')
        self.p.commit("lead: bad mode")
        self.p.write("tickets/T-042-01-returns-api.md", self.p.read("tickets/T-042-01-returns-api.md") + "\n")
        scope, _ = self.gate()
        self.assertIn("outside the build play's write set", scope["summary"])
        self.assertIn("scope.hidden_files must be warn or fail", scope["summary"])

    def test_a_git_failure_fails_closed(self) -> None:
        import tempfile

        from sdlc import gitutil

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(gitutil.GitError):
                gitutil.hidden(Path(tmp))


class HiddenFilesRepo(unittest.TestCase):
    """gitutil.hidden on a bare repository: the whole repository, and names it cannot decode."""

    def setUp(self) -> None:
        import tempfile

        from helpers import git

        self.git = git
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "kit@example.com")
        git(self.root, "config", "user.name", "kit tests")
        for f in ("prod/app.py", "shared/lib.py"):
            (self.root / f).parent.mkdir(parents=True, exist_ok=True)
            (self.root / f).write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def commit(self) -> None:
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "init")

    def test_a_nested_product_sees_hidden_files_outside_its_root(self) -> None:
        from sdlc import gitutil

        self.commit()
        self.git(self.root, "update-index", "--assume-unchanged", "shared/lib.py")
        self.assertEqual(gitutil.hidden(self.root / "prod"), ["shared/lib.py"])

    def test_an_undecodable_name_still_counts(self) -> None:
        import os

        from sdlc import gitutil

        name = os.path.join(os.fsencode(self.root), b"lat\xe9.py")
        with open(name, "wb") as fh:
            fh.write(b"x = 1\n")
        self.commit()
        self.git(self.root, "update-index", "--assume-unchanged", "--", "lat\udce9.py")
        self.assertEqual(len(gitutil.hidden(self.root)), 1)
        self.git(self.root, "update-index", "--no-assume-unchanged", "--", "lat\udce9.py")
        # git clears skip-worktree on files on disk under sparse checkout unless told not to.
        self.git(self.root, "config", "sparse.expectFilesOutsideOfPatterns", "true")
        self.git(self.root, "sparse-checkout", "set", "--no-cone", "/*", "!/lat*")
        if not os.path.lexists(name):
            with open(name, "wb") as fh:  # back on disk, outside the patterns
                fh.write(b"x = 1\n")
        self.git(self.root, "update-index", "--skip-worktree", "--", "lat\udce9.py")
        self.assertEqual(len(gitutil.hidden(self.root)), 1)  # on disk, but no name to look it up by

    def test_a_dangling_symlink_on_disk_counts(self) -> None:
        import os

        from sdlc import gitutil

        os.symlink("nowhere", self.root / "link")
        self.commit()
        self.git(self.root, "config", "sparse.expectFilesOutsideOfPatterns", "true")
        self.git(self.root, "sparse-checkout", "set", "--no-cone", "/*", "!/link")
        if not os.path.lexists(self.root / "link"):
            os.symlink("nowhere", self.root / "link")  # back on disk, still outside the patterns
        self.assertEqual(gitutil.hidden(self.root), ["link"])


class LockfileScope(unittest.TestCase):
    """Pilot finding 7: scope.always_allowed (the node profiles list the lockfiles) passed every
    scope check, so a committed dependency change shipped in any PR unreviewed."""

    def setUp(self) -> None:
        from helpers import git

        self.git = git
        self.p = ProductRepo()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nalways_allowed = ["package-lock.json"]\n'
                     'lead_code = "fail"\n')
        self.p.commit("lead: lockfiles in scope")

    def tearDown(self) -> None:
        self.p.close()

    def build_scope(self) -> dict:
        self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        return {x["name"]: x for x in ev["checks"]}["scope"]

    def start_build(self) -> None:
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertEqual(code, 0, out)
        self.p.commit("start T-042-02")
        self.git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")

    def test_a_lockfile_left_in_the_working_tree_stays_out_of_scope(self) -> None:
        self.start_build()
        self.p.write("package-lock.json", "{}\n")  # untracked, as `npm install` leaves it
        c = self.build_scope()
        self.assertEqual(c["status"], "pass", c)
        self.assertFalse([d for d in c["details"] if "package-lock.json" in d], c)

    def test_a_committed_lockfile_is_judged_by_the_build_write_set(self) -> None:
        self.start_build()
        self.p.write("package-lock.json", "{}\n")
        self.p.commit("build: lockfile")
        c = self.build_scope()
        self.assertIn("out of area (the approving review must name it under ## Out of area): package-lock.json",
                      c["details"])

    def test_the_test_play_answers_only_for_lockfile_changes_it_commits(self) -> None:
        self.start_build()
        self.p.write("package-lock.json", "{}\n")
        self.p.commit("build: lockfile")
        start = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.p.write("package-lock.json", '{"lockfileVersion": 3}\n')  # `npm install` in the test play
        self.p.sdlc("gate", "test", "T-042-02", "--since", start, "--only", "scope")
        c = json.loads(self.p.read(".sdlc-run/T-042-02.test.json"))["checks"][0]
        self.assertEqual(c["status"], "pass", c)
        self.p.commit("test: lockfile")
        self.p.sdlc("gate", "test", "T-042-02", "--since", start, "--only", "scope")
        c = json.loads(self.p.read(".sdlc-run/T-042-02.test.json"))["checks"][0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("outside test write set: package-lock.json", c["details"])

    def test_an_untracked_lockfile_is_not_an_out_of_area_flag(self) -> None:
        from sdlc import config
        from sdlc.gate import Gate

        self.start_build()
        self.p.write("package-lock.json", "{}\n")
        self.assertNotIn("package-lock.json", Gate(config.load(self.p.root), "pr", "T-042-02", "main").out_of_area())
        self.p.commit("build: lockfile")
        self.assertIn("package-lock.json", Gate(config.load(self.p.root), "pr", "T-042-02", "main").out_of_area())

    def test_the_review_still_sees_a_lockfile_the_build_committed(self) -> None:
        # The review play starts after the build (`since`), but its out-of-area list is the
        # whole branch's: the PR gate will ask the review to name this file.
        from sdlc import config
        from sdlc.gate import Gate

        self.start_build()
        self.p.write("package-lock.json", "{}\n")
        self.p.commit("build: lockfile")
        start = self.git(self.p.root, "rev-parse", "HEAD").strip()
        review = Gate(config.load(self.p.root), "review", "T-042-02", "main", since=start)
        self.assertIn("package-lock.json", review.out_of_area())

    def test_scope_judges_every_lockfile_as_committed_when_git_cannot_say(self) -> None:
        from unittest import mock

        from sdlc import gitutil

        self.start_build()
        self.p.write("package-lock.json", "{}\n")  # untracked, yet unprovable without git
        with mock.patch.object(gitutil, "committed_between", side_effect=gitutil.GitError("no history")):
            from sdlc import config
            from sdlc.gate import Gate

            self.assertIn("package-lock.json", Gate(config.load(self.p.root), "pr", "T-042-02", "main").out_of_area())

    def test_a_lead_pr_that_commits_a_lockfile_is_judged_by_lead_code(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "deps")
        self.p.write("package-lock.json", "{}\n")
        code, out = self.p.sdlc("gate", "pr", "--base", "main", "-v")
        self.assertEqual(code, 0, out)  # uncommitted: nothing ships
        self.p.commit("bump deps")
        code, out = self.p.sdlc("gate", "pr", "--base", "main", "-v")
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: package-lock.json", out)


class Baseline(unittest.TestCase):
    """Hangout pilot: a product adopting the kit with a red main could not pass any ticket
    gate, because every gate also runs the repo-wide checks. sdlc-baseline.json carries the
    failures main already has; anything new still fails, and the baseline only shrinks."""

    DRIFT = ('("api", "GET", "/api/orders/{id}/returns", get_returns),',
             '("api", "GET", "/api/orders/{id}/returns", get_returns),\n    ("api", "DELETE", "/api/orders/{id}", get_returns),')
    DRIFT2 = ('("api", "GET", "/api/orders/{id}/returns", get_returns),',
              '("api", "GET", "/api/orders/{id}/returns", get_returns),\n    ("api", "PUT", "/api/orders/{id}", get_returns),')

    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def contracts(self) -> dict:
        code, out = self.p.sdlc("gate", "ci", "--only", "contracts")
        ev = json.loads(self.p.read(".sdlc-run/ci.json"))
        return {c["name"]: c for c in ev["checks"]}["contracts"]

    def red_main_with_baseline(self) -> None:
        self.p.write("app/server.py", self.p.read("app/server.py").replace(*self.DRIFT))
        self.p.commit("main is red: a route CONTRACTS does not declare")
        code, out = self.p.sdlc("baseline")
        self.assertEqual(code, 0, out)
        self.assertIn("1 known failure(s) in 1 check(s)", out)
        self.p.commit("lead: baseline")

    def test_known_failures_pass_and_new_ones_fail(self) -> None:
        self.assertEqual(self.contracts()["status"], "pass")
        self.p.write("app/server.py", self.p.read("app/server.py").replace(*self.DRIFT))
        self.assertEqual(self.contracts()["status"], "fail")  # no baseline: red
        self.p.commit("main is red")
        self.p.sdlc("baseline")
        self.p.commit("lead: baseline")
        c = self.contracts()
        self.assertEqual(c["status"], "pass", c)
        self.assertIn("BASELINED: 1 known failure(s)", c["summary"])
        self.p.write("app/server.py", self.p.read("app/server.py").replace(*self.DRIFT2))
        c = self.contracts()
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["details"][0], "new: route in code but not in CONTRACTS: PUT /api/orders/{} (routes.command)")

    def test_fixed_failures_must_be_pruned(self) -> None:
        self.red_main_with_baseline()
        self.p.write("app/server.py", self.p.read("app/server.py").replace(self.DRIFT[1], self.DRIFT[0]))
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 baselined failure(s) no longer fail; run `sdlc baseline --prune`", out)
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertIn("pruned 1 failure(s) across 1 key(s) that no longer fail", out)
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)

    def test_baseline_only_shrinks(self) -> None:
        from helpers import git

        self.red_main_with_baseline()
        git(self.p.root, "checkout", "-q", "-b", "lead/hide-more")
        data = json.loads(self.p.read("sdlc-baseline.json"))
        data["checks"]["contracts"]["route in code but not in CONTRACTS: PUT /api/orders/{} (routes.command)"] = 1
        self.p.write("sdlc-baseline.json", json.dumps(data))
        self.p.commit("hide a new failure")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("sdlc-baseline.json: may only shrink, but adds contracts: route in code but not in "
                      "CONTRACTS: PUT /api/orders/{} (routes.command)", out)

    def test_changing_real_stack_keeps_unproven_tickets_known(self) -> None:
        # Hangout pilot: the baseline was written while tests.real_stack was ["integration"];
        # the lead then set it to integration and e2e (this product's default). Every known
        # "done without real-stack proof" entry turned into a new failure no PR could fix.
        from helpers import git

        self.p.write("tests/test_http_returns.py", self.p.read("tests/test_http_returns.py")
                     .replace('"""T-042-01/AC-1"""', '"""mounted"""').replace('"""T-042-01/AC-4"""', '"""404"""'))
        self.p.commit("main: T-042-01 lost its real-stack tags")
        legacy = "T-042-01: done, but no passing integration test carries its tag"
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"ac-coverage": {legacy: 1}}}))
        self.p.commit("lead: baseline written by an older kit")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertEqual(code, 0, out)
        self.assertIn("BASELINED: 1 known failure(s)", out)
        # Rewriting the file in the new form is not growth.
        git(self.p.root, "checkout", "-q", "-b", "lead/rewrite")
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"ac-coverage": {
            "T-042-01: done, but no passing real-stack test carries its tag": 1}}}))
        self.p.commit("lead: baseline in the new form")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertEqual(code, 0, out)
        # An entry for another ticket does not cover this one.
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"ac-coverage": {
            legacy.replace("T-042-01", "T-042-09"): 1}}}))
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 new failure(s) not in sdlc-baseline.json", out)

    UNPROVEN = "T-042-01: done, but no passing integration test carries its tag"

    def unproven_t1(self) -> None:
        self.p.write("tests/test_http_returns.py", self.p.read("tests/test_http_returns.py")
                     .replace('"""T-042-01/AC-1"""', '"""mounted"""').replace('"""T-042-01/AC-4"""', '"""404"""'))
        self.p.commit("main: T-042-01 lost its real-stack tags")

    def ac_waiver(self, wid: str, key: str, renews: str = "") -> str:
        import datetime as dt

        exp = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        return (f'[[waiver]]\nid = "{wid}"\ncheck = "ac-coverage"\nkey = {json.dumps(key)}\ncount = 1\n'
                f'owner = "lead"\nreason = "test play next sprint"\nexpires = {exp}\n'
                + (f'renews = "{renews}"\n' if renews else ""))

    def test_a_waiver_in_an_older_kits_wording_still_covers(self) -> None:
        # A waiver written for the old key (suite names in it) must keep covering after the
        # upgrade; a PR could not fix it, since a changed waiver covers nothing in its own PR.
        from helpers import git

        self.unproven_t1()
        self.p.write("sdlc-waivers.toml", self.ac_waiver("W-1", self.UNPROVEN))
        self.p.commit("lead: waive T-042-01's real-stack proof, in an older kit's wording")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertEqual(code, 0, out)
        self.assertIn("WAIVED: 1 failure(s)", out)
        # Renewing it in the new wording keeps its coverage in the renewal's own PR.
        git(self.p.root, "checkout", "-q", "-b", "lead/renew")
        self.p.write("sdlc-waivers.toml", self.ac_waiver(
            "W-2", "T-042-01: done, but no passing real-stack test carries its tag", renews="W-1"))
        self.p.commit("lead: renew W-1 in the new wording")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage", "--base", "main")
        self.assertEqual(code, 0, out)

    def test_prune_reads_an_older_kits_wording(self) -> None:
        # Two old keys for one ticket (written under two suite lists) are one failure that
        # occurred twice: one stays known, one is pruned, and the file is written in the new form.
        self.unproven_t1()
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"ac-coverage": {
            self.UNPROVEN: 1, self.UNPROVEN.replace("integration", "integration/e2e"): 1}}}))
        self.p.commit("lead: baseline written by an older kit")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertIn("pruned 1 failure(s)", out)
        self.assertEqual(json.loads(self.p.read("sdlc-baseline.json"))["checks"], {"ac-coverage": {
            "T-042-01: done, but no passing real-stack test carries its tag": 1}})

    def test_a_ticket_cannot_create_the_baseline(self) -> None:
        from helpers import git

        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.p.commit("start T-042-02")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.p.write("sdlc-baseline.json", '{"version": 1, "checks": {"contracts": ["anything"]}}')
        self.p.commit("sneak a baseline in")
        code, out = self.p.sdlc("gate", "build", "T-042-02", "--only", "immutable", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("created by a ticket; only the lead adds the baseline", out)

    def test_failing_tests_are_baselined_by_name(self) -> None:
        def add_failing(cls: str, test: str) -> None:
            self.p.write("app/test_returns.py", self.p.read("app/test_returns.py") +
                         f"\n\nclass {cls}(unittest.TestCase):\n    def {test}(self) -> None:\n        self.fail('x')\n")

        add_failing("Known", "test_known_broken")
        self.p.commit("main is red: a failing unit test")
        self.assertEqual(self.p.sdlc("baseline")[0], 0)
        self.assertIn("test_known_broken", self.p.read("sdlc-baseline.json"))
        self.p.commit("lead: baseline")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit")
        self.assertEqual(code, 0, out)
        self.assertIn("BASELINED: 1 known failure(s)", out)
        add_failing("AlsoBroken", "test_new_break")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit")
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 new failure(s) not in sdlc-baseline.json", out)
        self.assertIn("test_new_break", out)

    def test_trace_problems_are_baselined(self) -> None:
        # Hangout: 30 shipped v0 tickets have no build evidence, so `sdlc trace` (a CI step)
        # failed every run even with every gate check baselined.
        evidence = self.p.read("evidence/T-042-01.build.json")
        (self.p.root / "evidence/T-042-01.build.json").unlink()
        self.p.commit("main is red: a done ticket without evidence")
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR T-042-01: done without passing build evidence", out)
        self.assertEqual(self.p.sdlc("baseline")[0], 0)
        self.assertIn("T-042-01: done without passing build evidence", self.p.read("sdlc-baseline.json"))
        self.p.commit("lead: baseline")
        code, out = self.p.sdlc("trace")
        self.assertEqual(code, 0, out)
        self.assertIn("known trace problem(s) from sdlc-baseline.json, none new", out)
        # A ticket shipped after the baseline must still be proven.
        ticket = self.p.read("tickets/T-042-02-order-page.md")
        self.p.write("tickets/T-042-02-order-page.md", ticket.replace("status: ready", "status: done"))
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR T-042-02: done without passing build evidence", out)
        self.p.write("tickets/T-042-02-order-page.md", ticket)
        # Proving the old ticket leaves stale entries: trace asks for a prune, then passes.
        self.p.write("evidence/T-042-01.build.json", evidence)
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR fixed, still in sdlc-baseline.json: T-042-01: done without passing build evidence", out)
        self.p.sdlc("baseline", "--prune")
        self.assertNotIn("trace", json.loads(self.p.read("sdlc-baseline.json"))["checks"])
        self.assertEqual(self.p.sdlc("trace")[0], 0)

    def test_trace_baseline_only_shrinks(self) -> None:
        from helpers import git

        self.red_main_with_baseline()
        git(self.p.root, "checkout", "-q", "-b", "lead/hide-trace")
        data = json.loads(self.p.read("sdlc-baseline.json"))
        data["checks"]["trace"] = ["T-042-02: done without passing build evidence"]
        self.p.write("sdlc-baseline.json", json.dumps(data))
        self.p.commit("hide a trace problem")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("may only shrink, but adds trace: T-042-02: done without passing build evidence", out)



class BaselineRenames(unittest.TestCase):
    """ADR-0002 step 4a: Hangout's baseline keys embed paths, so moving a file turned every
    known failure in it into a new one plus a stale one. Version 2 counts each key and follows
    the renames git sees since the baseline was written."""

    TSC = ("import sys\nfrom pathlib import Path\nbad = 0\n"
           "for f in sorted(Path('app').rglob('*.py')):\n"
           "    for n, line in enumerate(f.read_text().splitlines(), 1):\n"
           "        if 'TYPEERR' in line:\n"
           "            print(f'{f.as_posix()}({n},1): error TS2345: bad argument')\n"
           "            bad += 1\n"
           "sys.exit(1 if bad else 0)\n")

    def setUp(self) -> None:
        from helpers import git

        from helpers import git

        self.git = git
        self.p = ProductRepo()
        self.p.write("tools/fake_tsc.py", self.TSC)
        cfg = self.p.read("sdlc.toml").replace('typecheck = "python tools/lint.py --types"',
                                                f"typecheck = '\"{Path(sys.executable).as_posix()}\" tools/fake_tsc.py'")
        self.p.write("sdlc.toml", cfg)
        self.p.write("app/legacy.py", "A = 1  # TYPEERR\nB = 2  # TYPEERR\n")
        self.p.commit("main is red: two type errors in one file")
        code, out = self.p.sdlc("baseline")
        self.assertEqual(code, 0, out)
        self.p.commit("lead: baseline")

    def tearDown(self) -> None:
        self.p.close()

    def typecheck(self) -> tuple[int, str]:
        return self.p.sdlc("gate", "ci", "--only", "typecheck")

    def test_the_baseline_counts_each_key(self) -> None:
        data = json.loads(self.p.read("sdlc-baseline.json"))
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["checks"]["typecheck"], {"app/legacy.py: TS2345": 2})

    def test_a_moved_file_keeps_its_known_failures_on_the_branch_and_after_the_merge(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "lead/move")
        self.git(self.p.root, "mv", "app/legacy.py", "app/old_legacy.py")
        self.p.commit("move legacy")
        code, out = self.typecheck()
        self.assertEqual(code, 0, out)
        self.assertIn("BASELINED: 2 known failure(s)", out)
        self.git(self.p.root, "checkout", "-q", "main")
        self.git(self.p.root, "merge", "-q", "--no-ff", "-m", "merge the move", "lead/move")
        code, out = self.typecheck()  # main's gate ci: no prune asked for, nothing new
        self.assertEqual(code, 0, out)
        self.assertIn("BASELINED: 2 known failure(s)", out)

    def test_one_more_failure_in_a_moved_file_still_fails(self) -> None:
        self.git(self.p.root, "mv", "app/legacy.py", "app/old_legacy.py")
        self.p.write("app/old_legacy.py", self.p.read("app/old_legacy.py") + "C = 3  # TYPEERR\n")
        self.p.commit("move legacy and add an error")
        code, out = self.typecheck()
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 new failure(s) not in sdlc-baseline.json", out)
        self.assertIn("new: app/old_legacy.py: TS2345", out)

    def test_a_prune_after_a_move_writes_the_new_path_and_does_not_grow(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "lead/move-and-fix")
        self.git(self.p.root, "mv", "app/legacy.py", "app/old_legacy.py")
        self.p.write("app/old_legacy.py", "A = 1  # TYPEERR\nB = 2\n")
        self.p.commit("move legacy, fix one error")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 1 failure(s) across 1 key(s)", out)
        self.assertEqual(json.loads(self.p.read("sdlc-baseline.json"))["checks"]["typecheck"],
                         {"app/old_legacy.py: TS2345": 1})
        self.p.commit("prune")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable,typecheck", "--base", "main")
        self.assertEqual(code, 0, out)
        # Raising a count is growth, under the new path as under the old.
        data = json.loads(self.p.read("sdlc-baseline.json"))
        data["checks"]["typecheck"]["app/old_legacy.py: TS2345"] = 3
        self.p.write("sdlc-baseline.json", json.dumps(data))
        self.p.commit("hide two more")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("may only shrink, but adds typecheck: app/old_legacy.py: TS2345", out)

    def test_a_prune_keeps_the_entries_of_a_check_that_failed_as_a_whole(self) -> None:
        # Hangout pilot finding 15: ac-coverage errored ("no test command wrote JUnit"), its only
        # finding was "ac-coverage: fails", and the prune dropped all 241 entries.
        self.p.write("tools/fake_tsc.py", "import sys\nsys.exit(2)  # crashed: names no failure\n")
        self.p.commit("the type checker crashes")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 0 failure(s) across 0 key(s)", out)
        self.assertIn("kept all 2 known typecheck failure(s): it failed as a whole", out)
        self.assertEqual(json.loads(self.p.read("sdlc-baseline.json"))["checks"]["typecheck"],
                         {"app/legacy.py: TS2345": 2})

    def test_a_prune_keeps_the_entries_of_a_check_that_did_not_run(self) -> None:
        cfg = self.p.read("sdlc.toml")
        self.p.write("sdlc.toml", cfg + '\n[gate]\nci = ["artifacts", "immutable"]\n')
        self.p.commit("ci runs no type check")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("kept all 2 known typecheck failure(s): it did not run", out)
        self.assertEqual(json.loads(self.p.read("sdlc-baseline.json"))["checks"]["typecheck"],
                         {"app/legacy.py: TS2345": 2})

    def test_a_prune_still_drops_what_a_check_that_ran_no_longer_reports(self) -> None:
        self.p.write("app/legacy.py", "A = 1\nB = 2  # TYPEERR\n")
        self.p.commit("fix one error")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 1 failure(s) across 1 key(s)", out)
        self.assertNotIn("kept all", out)
        self.assertEqual(json.loads(self.p.read("sdlc-baseline.json"))["checks"]["typecheck"],
                         {"app/legacy.py: TS2345": 1})

    def test_a_prune_counts_failures_and_keys_apart(self) -> None:
        # Pilot finding 6: "pruned 14 entries" was 7 keys that each failed twice.
        self.p.write("app/legacy.py", "A = 1\nB = 2\n")
        self.p.commit("fix both errors")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 2 failure(s) across 1 key(s) that no longer fail", out)
        self.assertNotIn("typecheck", json.loads(self.p.read("sdlc-baseline.json"))["checks"])

    def test_an_uncommitted_edit_to_the_baseline_is_renamed_too(self) -> None:
        self.git(self.p.root, "mv", "app/legacy.py", "app/old_legacy.py")
        self.p.commit("move legacy")
        # A hand edit that keeps the old path (here: back to the version 1 shape), not committed.
        self.p.write("sdlc-baseline.json", json.dumps(
            {"version": 1, "checks": {"typecheck": ["app/legacy.py: TS2345", "app/legacy.py: TS2345"]}}))
        code, out = self.typecheck()
        self.assertEqual(code, 0, out)
        self.assertIn("BASELINED: 2 known failure(s)", out)

    def test_a_version_1_baseline_is_still_read(self) -> None:
        self.p.write("sdlc-baseline.json", json.dumps(
            {"version": 1, "checks": {"typecheck": ["app/legacy.py: TS2345", "app/legacy.py: TS2345"]}}))
        self.p.commit("lead: a v1 baseline")
        code, out = self.typecheck()
        self.assertEqual(code, 0, out)
        self.p.write("app/legacy.py", self.p.read("app/legacy.py") + "C = 3  # TYPEERR\n")
        code, out = self.typecheck()
        self.assertNotEqual(code, 0, out)
        self.assertIn("new: app/legacy.py: TS2345", out)


class BaselineJUnit(unittest.TestCase):
    """Review of kit #29: a suite that only partly ran (one test file failed to import) still
    names other failures, so its baselined tests that did not run looked fixed to a prune."""

    JUNIT = ("import sys\nfrom pathlib import Path\n"
             "out = sys.argv[sys.argv.index('--out') + 1]\n"
             "cases = [l.split() for l in Path('cases.txt').read_text().splitlines() if l.strip()]\n"
             "xml = ['<testsuite>']\n"
             "for name, status in cases:\n"
             "    body = {'failed': '<failure/>', 'skipped': '<skipped/>'}.get(status, '')\n"
             "    xml.append(f'<testcase classname=\"T\" name=\"{name}\">{body}</testcase>')\n"
             "Path(out).write_text(''.join(xml) + '</testsuite>')\n"
             "sys.exit(1 if any(s == 'failed' for _, s in cases) else 0)\n")

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write("tools/fake_junit.py", self.JUNIT)
        cfg = self.p.read("sdlc.toml").replace(
            'unit = "python tools/junit.py --start app --out {junit}"',
            f"unit = '\"{Path(sys.executable).as_posix()}\" tools/fake_junit.py --out {{junit}}'")
        self.p.write("sdlc.toml", cfg)
        self.cases("a failed", "b failed", "c passed")
        self.p.commit("main is red: two failing unit tests")
        code, out = self.p.sdlc("baseline")
        self.assertEqual(code, 0, out)
        self.p.commit("lead: baseline")

    def tearDown(self) -> None:
        self.p.close()

    def cases(self, *lines: str) -> None:
        self.p.write("cases.txt", "\n".join(lines) + "\n")

    def unit(self) -> dict:
        return json.loads(self.p.read("sdlc-baseline.json"))["checks"]["unit"]

    def test_the_baseline_names_each_failing_test(self) -> None:
        self.assertEqual(self.unit(), {"T a": 1, "T b": 1})

    def test_a_prune_keeps_a_known_failure_whose_test_did_not_run(self) -> None:
        self.cases("a failed", "c passed")  # b's file failed to import: b is simply absent
        self.p.commit("b does not run")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("kept 1 known unit failure(s) whose tests the JUnit did not report as passed", out)
        self.assertEqual(self.unit(), {"T a": 1, "T b": 1})

    def test_a_prune_keeps_a_known_failure_whose_test_was_skipped(self) -> None:
        self.cases("a failed", "b skipped", "c passed")
        self.p.commit("b is skipped")
        self.p.sdlc("baseline", "--prune")
        self.assertEqual(self.unit(), {"T a": 1, "T b": 1})

    def test_a_prune_counts_tests_that_share_a_name(self) -> None:
        # CodeRabbit on #30: one of two same-named failures still fails, the other did not run.
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"unit": {"T a": 2, "T b": 1}}}))
        self.p.commit("lead: baseline counts a twice")
        self.cases("a failed", "a skipped", "b failed", "c passed")
        self.p.commit("one a is skipped")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("kept 1 known unit failure(s) whose tests the JUnit did not report as passed", out)
        self.assertEqual(self.unit(), {"T a": 2, "T b": 1})

    def test_a_prune_drops_a_whole_suite_entry_once_the_suite_reports_its_tests(self) -> None:
        # CodeRabbit on #30: "unit: fails" names no test, so no passed test ever matched it and
        # the restore kept it forever, ready to absorb a later crash of the suite.
        self.p.write("sdlc-baseline.json", json.dumps({"version": 2, "checks": {"unit": {"unit: fails": 1}}}))
        self.p.commit("lead: the suite used to crash")
        self.cases("a passed", "b passed", "c passed")
        self.p.commit("the suite runs and passes")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 1 failure(s) across 1 key(s)", out)
        self.assertNotIn("unit", json.loads(self.p.read("sdlc-baseline.json"))["checks"])

    def test_a_prune_drops_a_known_failure_whose_test_now_passes(self) -> None:
        self.cases("a failed", "b passed", "c passed")
        self.p.commit("fix b")
        code, out = self.p.sdlc("baseline", "--prune")
        self.assertEqual(code, 0, out)
        self.assertIn("pruned 1 failure(s) across 1 key(s)", out)
        self.assertNotIn("kept", out)
        self.assertEqual(self.unit(), {"T a": 1})


class Waivers(unittest.TestCase):
    """ADR-0002 step 4b: sdlc-waivers.toml. A waiver on the base branch covers up to its count
    of a failure main already has; it is owned, dated from git, and expires."""

    def setUp(self) -> None:
        import datetime as dt

        from helpers import git

        self.git, self.dt = git, dt
        self.today = dt.date.today()
        self.p = ProductRepo()
        self.p.write("tools/fake_tsc.py", BaselineRenames.TSC)
        cfg = self.p.read("sdlc.toml").replace('typecheck = "python tools/lint.py --types"',
                                                f"typecheck = '\"{Path(sys.executable).as_posix()}\" tools/fake_tsc.py'")
        self.p.write("sdlc.toml", cfg)
        self.p.write("app/legacy.py", "A = 1  # TYPEERR\nB = 2  # TYPEERR\n")
        self.p.commit("main is red: two type errors the lead cannot fix today")

    def tearDown(self) -> None:
        self.p.close()

    def waive(self, *entries: dict) -> None:
        out = []
        for e in entries:
            w = {"id": "W-1", "check": "typecheck", "key": "app/legacy.py: TS2345", "count": 2,
                 "owner": "lead", "reason": "vendor types land next sprint",
                 "expires": self.today + self.dt.timedelta(days=30), **e}
            out.append("[[waiver]]\n" + "".join(
                f"{k} = {v.isoformat() if isinstance(v, self.dt.date) else json.dumps(v)}\n" for k, v in w.items()))
        self.p.write("sdlc-waivers.toml", "\n".join(out))

    def typecheck(self, *extra: str) -> tuple[int, str]:
        return self.p.sdlc("gate", "ci", "--only", "typecheck", *extra)

    def test_a_waiver_on_main_covers_its_count_and_says_who_owns_it(self) -> None:
        self.assertNotEqual(self.typecheck()[0], 0)
        self.waive({})
        self.p.commit("lead: waive the vendor type errors")
        code, out = self.typecheck()
        self.assertEqual(code, 0, out)
        self.assertIn("WAIVED: 2 failure(s) under sdlc-waivers.toml, none new", out)
        exp = (self.today + self.dt.timedelta(days=30)).isoformat()
        self.assertIn(f"waived: app/legacy.py: TS2345: W-1 (owner lead, expires {exp})", out)  # shown on a pass
        ev = json.loads(self.p.read(".sdlc-run/ci.json"))
        tc = {c["name"]: c for c in ev["checks"]}["typecheck"]
        self.assertEqual(len(tc["waived"]), 2)

    def test_one_more_occurrence_than_the_count_fails(self) -> None:
        self.waive({})
        self.p.commit("lead: waive")
        self.p.write("app/legacy.py", self.p.read("app/legacy.py") + "C = 3  # TYPEERR\n")
        code, out = self.typecheck()
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 new failure(s) not in sdlc-baseline.json", out)

    def test_a_branch_cannot_waive_its_own_failure(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "lead/waive")
        self.waive({})
        self.p.commit("waive on a branch")
        code, out = self.typecheck("--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("pending: W-1 applies once it is on main", out)
        # Raising a count on a branch is a change too: neither version applies there.
        self.git(self.p.root, "checkout", "-q", "main")
        self.git(self.p.root, "merge", "-q", "--no-ff", "-m", "merge", "lead/waive")
        self.assertEqual(self.typecheck()[0], 0)
        self.git(self.p.root, "checkout", "-q", "-b", "build/more")
        self.p.write("app/legacy.py", self.p.read("app/legacy.py") + "C = 3  # TYPEERR\n")
        self.waive({"count": 3})
        self.p.commit("raise the count with the new failure")
        code, out = self.typecheck("--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("pending: W-1 applies once it is on main", out)

    def test_a_waiver_that_covers_nothing_fails_gate_ci_until_removed(self) -> None:
        self.waive({})
        self.p.commit("lead: waive")
        self.p.write("app/legacy.py", "A = 1\nB = 2\n")
        self.p.commit("fix the type errors")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 waiver(s) cover nothing; remove them from sdlc-waivers.toml", out)
        self.assertIn("stale waiver: W-1 (app/legacy.py: TS2345)", out)
        (self.p.root / "sdlc-waivers.toml").unlink()
        self.p.commit("lead: drop the waiver")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)

    def test_an_expired_waiver_fails_gate_ci_and_ticket_gates_only_report_it(self) -> None:
        self.waive({"expires": self.today - self.dt.timedelta(days=1)})
        self.p.commit("lead: a waiver that has run out")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn(f"ERROR W-1: expired on {self.today - self.dt.timedelta(days=1)} (owner lead: vendor types "
                      "land next sprint)", out)
        self.git(self.p.root, "checkout", "-q", "-b", "lead/notes")
        self.p.write("decisions/notes.md", "notes\n")
        self.p.commit("a lead doc")
        code, out = self.p.sdlc("gate", "pr", "--base", "main", "--verbose")
        self.assertIn("WARN W-1: expired on", out)
        waiver_line = next(line for line in out.splitlines() if " waivers " in line)
        self.assertTrue(waiver_line.startswith("PASS"), out)

    def test_the_gate_warns_14_days_before_expiry(self) -> None:
        self.waive({"expires": self.today + self.dt.timedelta(days=10)})
        self.p.commit("lead: a short waiver")
        code, out = self.typecheck()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN W-1: expires on", out)
        self.assertIn("in 10 day(s) (owner lead); renew it or fix the failure", out)
        code, out = self.p.sdlc("doctor")
        self.assertIn("note  waiver: W-1: expires on", out)

    def test_a_waiver_may_not_outlast_max_days_from_its_commit(self) -> None:
        self.waive({"expires": self.today + self.dt.timedelta(days=91)})
        self.p.commit("lead: too long")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn(f"more than 90 days after it was added on {self.today}", out)

    def test_a_backdated_commit_cannot_date_a_waiver(self) -> None:
        import subprocess

        from helpers import git_env

        self.waive({})
        self.git(self.p.root, "add", "-A")
        env = git_env(GIT_COMMITTER_DATE="2020-01-01T00:00:00Z", GIT_AUTHOR_DATE="2020-01-01T00:00:00Z")
        subprocess.run(["git", "commit", "-q", "-m", "backdated waiver"], cwd=self.p.root, env=env, check=True)
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("introduces W-1 dated before its parent", out)

    def test_a_renewal_keeps_coverage_and_the_chain_is_capped(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + "\n[waivers]\nmax_days = 10\n")
        self.waive({"expires": self.today + self.dt.timedelta(days=5)})
        self.p.commit("lead: a 10-day waiver policy and a short waiver")
        self.git(self.p.root, "checkout", "-q", "-b", "lead/renew")
        self.waive({"id": "W-2", "renews": "W-1", "expires": self.today + self.dt.timedelta(days=10)})
        self.p.commit("renew W-1")
        code, out = self.typecheck("--base", "main")
        self.assertEqual(code, 0, out)  # the renewal keeps W-1's coverage in its own PR
        self.git(self.p.root, "checkout", "-q", "main")
        self.git(self.p.root, "merge", "-q", "--no-ff", "-m", "merge the renewal", "lead/renew")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)
        # A second renewal past twice max_days from W-1's date is refused.
        self.git(self.p.root, "checkout", "-q", "-b", "lead/renew-again")
        self.waive({"id": "W-3", "renews": "W-2", "expires": self.today + self.dt.timedelta(days=21)})
        self.p.commit("renew again")
        code, out = self.p.sdlc("gate", "ci", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn(f"would make its renewal chain last past 20 days from {self.today}", out)

    def test_an_expired_renewal_keeps_nothing(self) -> None:
        self.waive({})
        self.p.commit("lead: waive")
        self.git(self.p.root, "checkout", "-q", "-b", "lead/renew")
        self.waive({"id": "W-2", "renews": "W-1", "expires": self.today - self.dt.timedelta(days=1)})
        self.p.commit("a renewal that has already run out")
        code, out = self.p.sdlc("gate", "ci", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("W-2 expires", out)
        self.assertIn("which has already passed", out)
        self.assertNotIn("WAIVED", out)

    def test_two_renewals_of_one_waiver_do_not_double_its_coverage(self) -> None:
        self.waive({})
        self.p.commit("lead: waive")
        self.git(self.p.root, "checkout", "-q", "-b", "lead/renew")
        self.p.write("app/legacy.py", self.p.read("app/legacy.py") + "C = 3  # TYPEERR\nD = 4  # TYPEERR\n")
        self.waive({"id": "W-2", "renews": "W-1"}, {"id": "W-3", "renews": "W-1"})
        self.p.commit("renew twice, add two failures")
        code, out = self.p.sdlc("gate", "ci", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("W-3 renews W-1, which another entry already renews", out)
        self.assertIn("2 new failure(s)", out)

    def test_a_bad_date_stops_mattering_once_its_waiver_is_gone(self) -> None:
        import subprocess

        from helpers import git_env

        self.waive({})
        self.git(self.p.root, "add", "-A")
        env = git_env(GIT_COMMITTER_DATE="2020-01-01T00:00:00Z", GIT_AUTHOR_DATE="2020-01-01T00:00:00Z")
        subprocess.run(["git", "commit", "-q", "-m", "backdated waiver"], cwd=self.p.root, env=env, check=True)
        self.assertIn("dated before its parent", self.p.sdlc("gate", "ci")[1])
        self.p.write("sdlc-waivers.toml", "")
        self.p.write("app/legacy.py", "A = 1\nB = 2\n")
        self.p.commit("lead: fix the errors and drop the waiver")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)
        self.assertNotIn("dated before its parent", out)

    def test_trace_json_lists_a_waived_problem_once(self) -> None:
        (self.p.root / "evidence/T-042-01.build.json").unlink()
        self.p.commit("main loses a shipped ticket's evidence")
        key = "T-042-01: done without passing build evidence"
        self.waive({"check": "trace", "key": key, "count": 1})
        self.p.commit("lead: waive it")
        data = json.loads(self.p.sdlc("trace", "--json")[1])
        self.assertTrue(any(w.startswith(key) for w in data["waived"]), data["waived"])
        self.assertNotIn(key, data["known"])
        self.assertNotIn(key, data["problems"])

    def test_the_hardened_preset_allows_no_renewal(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n')
        self.waive({"expires": self.today + self.dt.timedelta(days=5)})
        self.p.commit("lead: hardened, and a short waiver")
        self.git(self.p.root, "checkout", "-q", "-b", "lead/renew")
        self.waive({"id": "W-2", "renews": "W-1", "expires": self.today + self.dt.timedelta(days=20)})
        self.p.commit("try to renew")
        code, out = self.p.sdlc("gate", "ci", "--base", "main")
        self.assertNotEqual(code, 0, out)
        self.assertIn("W-2 renews W-1; the hardened preset allows no renewal", out)
        self.assertNotIn("WAIVED", out)  # and it keeps no coverage meanwhile

    def test_a_renewal_already_on_main_covers_nothing_once_hardened(self) -> None:
        (self.p.root / "evidence/T-042-01.build.json").unlink()
        key = "T-042-01: done without passing build evidence"
        self.waive({"check": "trace", "key": key, "count": 1, "expires": self.today + self.dt.timedelta(days=5)})
        self.p.commit("lead: waive a trace problem")
        self.waive({"id": "W-2", "renews": "W-1", "check": "trace", "key": key, "count": 1})
        self.p.commit("lead: renew it")
        self.assertIn(f"WAIVED {key}", self.p.sdlc("trace")[1])  # by default the renewal covers it
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n')
        self.p.commit("lead: hardened")
        code, out = self.p.sdlc("trace")
        self.assertNotIn(f"WAIVED {key}", out)
        self.assertIn(f"ERROR {key}", out)

    def test_the_hardened_preset_caps_waivers_at_30_days(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n[waivers]\nmax_days = 90\n')
        self.waive({"expires": self.today + self.dt.timedelta(days=45)})
        self.p.commit("lead: hardened with a 90-day override, and a 45-day waiver")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn(f"more than 30 days after it was added on {self.today}", out)
        code, out = self.p.sdlc("doctor")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR [waivers] max_days = 90 is above the hardened preset's 30; 30 applies", out)

    def test_a_waiver_for_a_process_check_is_refused(self) -> None:
        self.waive({"check": "scope"})
        self.p.commit("lead: try to waive scope")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("scope is never waivable", out)

    def test_trace_problems_can_be_waived(self) -> None:
        (self.p.root / "evidence/T-042-01.build.json").unlink()
        self.p.commit("main loses a shipped ticket's evidence")
        self.assertIn("ERROR T-042-01: done without passing build evidence", self.p.sdlc("trace")[1])
        self.waive({"check": "trace", "key": "T-042-01: done without passing build evidence", "count": 1})
        self.p.commit("lead: waive it")
        code, out = self.p.sdlc("trace")
        self.assertIn("WAIVED T-042-01: done without passing build evidence: W-1 (owner lead", out)
        self.assertNotIn("ERROR T-042-01: done without passing build evidence", out)



class PresetDoctor(unittest.TestCase):
    """ADR-0002 step 4c: doctor prints the resolved lists and fails a setting the preset forbids."""

    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def test_doctor_prints_what_the_preset_resolves_to(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "floor"\n')
        code, out = self.p.sdlc("doctor")
        self.assertIn("preset: floor", out)
        ci = next(line for line in out.splitlines() if line.strip().startswith("gate.ci:"))
        self.assertNotIn("smoke", ci)
        self.assertNotIn("duplication", ci)
        self.assertNotIn("drops", out)  # the floor preset is at the floor, not below it

    def test_doctor_fails_a_ci_list_below_the_floor(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "floor"\nci = ["artifacts"]\n')
        code, out = self.p.sdlc("doctor")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR gate.ci drops immutable, contracts, lint, typecheck, unit, ac-coverage, test-quality, build",
                      out)

    def test_doctor_fails_trust_unsigned_under_hardened(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n'
                     '\n[approval]\nmode = "forge"\nreviewers = ["rev"]\ntrust_unsigned = true\n')
        code, out = self.p.sdlc("doctor")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR [approval] trust_unsigned is forbidden by the hardened preset", out)

class HardenedLeadCode(unittest.TestCase):
    """Issue #27: under the hardened preset, code in a PR that moves no ticket fails, except an
    exact revert of code already on the base branch."""

    def setUp(self) -> None:
        from helpers import git

        self.git = git
        self.p = ProductRepo()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n')
        self.p.commit("lead: hardened")

    def tearDown(self) -> None:
        self.p.close()

    def edit(self, rel: str, line: str) -> None:
        self.p.write(rel, self.p.read(rel) + line)

    def lead_pr(self) -> tuple[int, str]:
        return self.p.sdlc("gate", "pr", "--base", "main", "--only", "scope", "-v")

    def test_code_without_a_ticket_fails(self) -> None:
        self.git(self.p.root, "checkout", "-q", "-b", "hotfix")
        self.edit("app/returns.py", "\n# hotfix\n")
        self.p.commit("hotfix")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/returns.py", out)

    def test_a_products_warn_is_refused(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[scope]\nlead_code = "warn"\n')
        self.p.commit("lead: warn only")
        code, out = self.p.sdlc("doctor")
        self.assertNotEqual(code, 0, out)
        self.assertIn("ERROR [scope] lead_code = 'warn' is forbidden by the hardened preset", out)
        self.test_code_without_a_ticket_fails()  # the stricter value holds meanwhile

    def test_an_exact_revert_of_base_branch_code_passes(self) -> None:
        self.edit("app/returns.py", "\n# a bad hotfix\n")
        self.p.commit("bad hotfix")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        code, out = self.lead_pr()
        self.assertEqual(code, 0, out)
        self.assertIn(f"exact revert of {bad[:7]}", out)

    def test_a_revert_branch_that_merges_the_base_is_no_exact_revert(self) -> None:
        # The merge reverts nothing, so the branch is not the reverts alone; rebase it instead.
        self.edit("app/returns.py", "\n# a bad hotfix\n")
        self.p.commit("bad hotfix")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        self.git(self.p.root, "checkout", "-q", "main")
        self.p.write("docs/later.md", "main moves on\n")
        self.p.commit("main moves on")
        self.git(self.p.root, "checkout", "-q", "undo")
        self.git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "main")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/returns.py", out)

    def test_a_revert_that_only_matches_ignoring_whitespace_fails(self) -> None:
        # A patch id ignores whitespace: this "revert" restores the line at another indent.
        line = '    "ord_2": [],\n'
        self.p.write("app/returns.py", self.p.read("app/returns.py").replace(line, ""))
        self.p.commit("drop ord_2")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        text = self.p.read("app/returns.py")
        anchor = '    "ord_3"'
        self.p.write("app/returns.py", text.replace(anchor, '"ord_2": [],\n' + anchor, 1))
        self.git(self.p.root, "commit", "-qam", f"Revert drop ord_2\n\nThis reverts commit {bad}.")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/returns.py", out)

    def test_a_revert_of_a_commit_not_on_the_base_branch_fails(self) -> None:
        # Reverting a side branch's deletion would land the deleted code as a "revert".
        self.git(self.p.root, "checkout", "-q", "-b", "side")
        self.p.write("app/backdoor.py", "def open_up():\n    return True\n")
        self.p.commit("add it")
        self.git(self.p.root, "rm", "-q", "app/backdoor.py")
        self.p.commit("drop it")
        dropped = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "main")
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", dropped)
        self.assertTrue((self.p.root / "app" / "backdoor.py").is_file())
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/backdoor.py", out)

    def test_an_uncommitted_edit_on_an_exact_revert_is_not_excused(self) -> None:
        self.edit("app/returns.py", "\n# a bad hotfix\n")
        self.p.commit("bad hotfix")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        self.edit("app/returns.py", "\n# not committed\n")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/returns.py", out)

    def test_an_exact_revert_excuses_nothing_when_git_cannot_list_uncommitted_edits(self) -> None:
        from unittest import mock

        from sdlc import gitutil

        self.edit("app/returns.py", "\n# a bad hotfix\n")
        self.p.commit("bad hotfix")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        from sdlc import config
        from sdlc.gate import Check, Gate

        g = Gate(config.load(self.p.root), "pr", None, "main")
        c = Check("scope")
        with mock.patch.object(gitutil, "dirty", side_effect=gitutil.GitError("diff failed")):
            g._lead_scope(c)
        self.assertEqual(c.status, "fail", c.summary)
        self.assertIn("outside the lead write set: app/returns.py", c.details)

    def test_a_file_the_revert_deletes_and_the_tree_recreates_is_not_excused(self) -> None:
        # `git diff HEAD` cannot see a file HEAD does not have: only the untracked list does.
        self.p.write("app/hotfix.py", "X = 1\n")
        self.p.commit("bad hotfix adds a module")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        self.p.write("app/hotfix.py", "X = 2\n")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/hotfix.py", out)

    def test_a_revert_with_an_extra_change_fails(self) -> None:
        self.edit("app/returns.py", "\n# a bad hotfix\n")
        self.p.commit("bad hotfix")
        bad = self.git(self.p.root, "rev-parse", "HEAD").strip()
        self.git(self.p.root, "checkout", "-q", "-b", "undo")
        self.git(self.p.root, "revert", "--no-edit", bad)
        self.edit("app/server.py", "\n# riding along\n")
        self.p.commit("and one more thing")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/server.py", out)
        # Folded into the revert commit itself, the extra line makes it no exact revert at all.
        self.git(self.p.root, "reset", "-q", "--soft", "HEAD~2")
        self.git(self.p.root, "commit", "-q", "-m", f"Revert bad hotfix\n\nThis reverts commit {bad}.")
        code, out = self.lead_pr()
        self.assertNotEqual(code, 0, out)
        self.assertIn("outside the lead write set: app/returns.py", out)


class NestedRevert(unittest.TestCase):
    """A product nested in a monorepo: an exact revert of a commit that also touched files outside
    the product is still exact (git apply in a subdirectory skips paths outside it)."""

    def test_a_whole_commit_revert_counts_from_a_nested_product(self) -> None:
        import tempfile

        from helpers import git
        from sdlc import gitutil

        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp)
            git(top, "init", "-q", "-b", "main")
            git(top, "config", "user.email", "t@example.invalid")
            git(top, "config", "user.name", "t")
            (top / "sub").mkdir()
            (top / "sub" / "a.py").write_text("A = 1\n", encoding="utf-8")
            (top / "top.txt").write_text("top\n", encoding="utf-8")
            git(top, "add", "-A")
            git(top, "commit", "-qm", "start")
            (top / "sub" / "a.py").write_text("A = 2\n", encoding="utf-8")
            (top / "top.txt").write_text("changed\n", encoding="utf-8")
            git(top, "commit", "-qam", "both")
            bad = git(top, "rev-parse", "HEAD").strip()
            git(top, "checkout", "-q", "-b", "undo")
            git(top, "revert", "--no-edit", bad)
            got = gitutil.exact_reverts(top / "sub", "main")
            self.assertIsNotNone(got)
            self.assertEqual(got[0][1], bad)


class StatusBoard(unittest.TestCase):
    """`sdlc status` lists every ticket with what it waits on; file mode keeps stored status."""

    def setUp(self) -> None:
        self.p = ProductRepo()
        rel = "tickets/T-042-01-returns-api.md"
        self.p.write(rel, self.p.read(rel).replace("status: done", "status: ready"))
        self.p.commit("lead: T-042-01 not shipped yet")

    def tearDown(self) -> None:
        self.p.close()

    def test_the_board_names_unfinished_dependencies(self) -> None:
        code, out = self.p.sdlc("status")
        self.assertEqual(code, 0, out)
        self.assertIn("T-042-01\tready\t-\t", out)
        self.assertIn("T-042-02\tready\twaiting on T-042-01\t", out)
        self.assertIn("2 ready", out)
        rows = {r["id"]: r for r in json.loads(self.p.sdlc("status", "--json")[1])}
        self.assertEqual(rows["T-042-02"]["pending"], ["T-042-01"])
        self.assertEqual(rows["T-042-02"]["depends_on"], ["T-042-01"])
        self.assertEqual(self.p.sdlc("next", "--all")[1].split("\t")[0], "T-042-01")
        self.assertNotIn("T-042-02", self.p.sdlc("next", "--all")[1])

    def test_starting_a_ticket_with_an_unknown_dependency_is_refused(self) -> None:
        rel = "tickets/T-042-01-returns-api.md"
        self.p.write(rel, self.p.read(rel).replace("depends_on: []", "depends_on: [T-042-99]"))
        self.p.commit("lead: a dependency that does not exist")
        code, out = self.p.sdlc("status", "T-042-01", "in_progress", "--as", "build")
        self.assertNotEqual(code, 0, out)
        self.assertIn("depends_on not done: T-042-99", out)

    def test_file_mode_does_not_derive_in_progress_from_branches(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-01")
        self.p.write("notes.txt", "x\n")
        git(self.p.root, "add", "-A")
        git(self.p.root, "commit", "-q", "-m", "work", "-m", "Sdlc-Ticket: T-042-01")
        git(self.p.root, "checkout", "-q", "main")
        self.assertEqual(self.p.sdlc("status", "T-042-01")[1].strip(), "ready")
        self.assertEqual(self.p.sdlc("next")[1].strip(), "T-042-01")


if __name__ == "__main__":
    unittest.main()
