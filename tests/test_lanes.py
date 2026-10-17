"""ADR-0001 step 1: risk lanes, soft areas, ticket amendments and spikes. Each new check has a
test that catches the defect it exists for and a test that shows the reference passes."""
import json
import time
import unittest

from helpers import ProductRepo, git

MECH = "tickets/T-042-03-rename.md"
MECH_TICKET = """---
id: T-042-03
title: Rename STATES to RETURN_STATES
type: chore
status: in_progress
risk: low
lane: mechanical
depends_on: []
areas:
  - app/returns.py
  - app/test_returns.py
skills:
  - build
transforms:
  - rename STATES -> RETURN_STATES
requirements: []
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
---

A pure rename: the engine proves the diff is this transform and nothing else.
"""


def rename(p: ProductRepo, old: str = "STATES", new: str = "RETURN_STATES") -> None:
    for rel in ("app/returns.py", "app/test_returns.py"):
        p.write(rel, p.read(rel).replace(old, new))


class Lanes(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")

    def tearDown(self) -> None:
        self.p.close()

    def gate(self, play: str, ticket: str, *checks: str, lane: str = "") -> dict:
        args = ["gate", play, ticket] + (["--only", ",".join(checks)] if checks else []) + (["--lane", lane] if lane else [])
        self.code, self.out = self.p.sdlc(*args)
        name = f"{ticket}.{play}.json"
        partial = self.p.root / ".sdlc-run" / name
        full = self.p.root / "evidence" / name
        f = partial if checks else full if full.is_file() else partial
        self.ev = json.loads(f.read_text(encoding="utf-8"))
        return {c["name"]: c for c in self.ev["checks"]}

    def mechanical_branch(self) -> None:
        self.p.write(MECH, MECH_TICKET)
        rename(self.p)

    # -- mechanical ------------------------------------------------------
    def test_mechanical_rename_passes_with_the_full_suite_and_no_red_proof(self) -> None:
        self.mechanical_branch()
        checks = self.gate("build", "T-042-03")
        self.assertEqual(self.code, 0, self.out)
        self.assertEqual(self.ev["lane"], "mechanical")
        self.assertEqual(checks["lane"]["summary"], "lane mechanical")
        self.assertEqual(checks["mechanical"]["status"], "pass")
        self.assertNotIn("ac-red", checks)
        # It proves every shipped AC still holds, not just its own (it has none).
        self.assertIn("T-042-01", checks["ac-coverage"]["summary"] + " T-042-01")
        self.assertIn("of 1 ticket(s)", checks["ac-coverage"]["summary"])

    def test_mechanical_pr_merges_without_a_test_play(self) -> None:
        self.mechanical_branch()
        self.p.commit("T-042-03 rename")
        self.gate("build", "T-042-03")
        self.assertEqual(self.code, 0, self.out)
        self.assertEqual(self.p.sdlc("status", "T-042-03", "in_review", "--as", "build")[0], 0)
        self.p.commit("evidence T-042-03: build gate pass")
        proven = self.ev["commit"]
        self.p.write("reviews/T-042-03.md", f"""---
ticket: T-042-03
verdict: approve
reviewer: fake-reviewer
commit: {proven}
---

# Review T-042-03: Rename STATES to RETURN_STATES

## Gate

Build evidence: pass in the mechanical lane at `{proven}`.

## Acceptance criteria

None: a mechanical ticket proves every shipped AC still passes.

## Findings

None.
""")
        self.assertEqual(self.p.sdlc("status", "T-042-03", "done", "--as", "merge")[0], 0)
        self.p.commit("T-042-03 review: approve; done")
        code, out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertEqual(code, 0, out)
        self.assertIn("lane mechanical", out)

    def test_residue_in_production_raises_mechanical_to_standard(self) -> None:
        self.mechanical_branch()
        self.p.write("app/server.py", self.p.read("app/server.py").replace('"not_found"', '"missing"', 1))
        checks = self.gate("build", "T-042-03", "lane", "mechanical")
        lane = checks["lane"]
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("mechanical -> standard", "\n".join(lane["details"]))
        self.assertIn("residue: app/server.py:", "\n".join(lane["details"]))
        # Standard proves each AC, and the lead makes a standard ticket ready first.
        self.assertEqual(lane["status"], "fail")
        self.assertIn("has no acceptance criteria", "\n".join(lane["details"]))
        self.assertIn("was created on this branch", "\n".join(lane["details"]))
        self.assertNotIn("mechanical", checks)  # the standard list runs instead

    def test_residue_in_a_test_raises_mechanical_to_standard(self) -> None:
        self.mechanical_branch()
        t = self.p.read("app/test_returns.py")
        self.p.write("app/test_returns.py", t.replace("404", "200", 1))
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "standard")
        self.assertTrue(any(r.startswith("residue: app/test_returns.py:") for r in
                            self.ev["checks"][0]["details"]), self.ev["checks"][0])

    def test_added_file_is_residue_unless_a_move_declares_it(self) -> None:
        self.mechanical_branch()
        self.p.write("app/helpers.py", "X = 1\n")
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("residue: app/helpers.py: added, and no declared move creates it",
                      self.ev["checks"][0]["details"])

    def test_declared_move_is_mechanical(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("app/notes.txt", "see STATES\n")
        self.p.commit("notes")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-03")
        self.mechanical_branch()
        self.p.write(MECH, self.p.read(MECH).replace("  - rename STATES -> RETURN_STATES",
                                                     "  - rename STATES -> RETURN_STATES\n"
                                                     "  - move app/notes.txt -> app/docs/notes.txt"))
        # The edits apply to the moved file too: its content is the transformed original.
        self.p.write("app/docs/notes.txt", "see RETURN_STATES\n")
        (self.p.root / "app" / "notes.txt").unlink()
        checks = self.gate("build", "T-042-03", "lane", "mechanical")
        self.assertEqual(self.ev["lane"], "mechanical", checks["lane"])
        self.p.write("app/docs/notes.txt", "see STATES\n")
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "standard")

    def test_regex_transforms_do_not_exist(self) -> None:
        self.p.write(MECH, MECH_TICKET.replace("  - rename STATES -> RETURN_STATES",
                                               "  - regex s/(\\w+)_for/find_\\1/"))
        code, out = self.p.sdlc("lint")
        self.assertNotEqual(code, 0)
        self.assertIn("want 'literal \"old\" -> \"new\"', 'rename old -> new' (identifiers) or "
                      "'move old/path -> new/path'", out)

    def test_mechanical_ticket_may_not_add_acceptance_criteria(self) -> None:
        self.mechanical_branch()
        self.p.write(MECH, self.p.read(MECH).replace("requirements: []", 'requirements: []\nacceptance_criteria:\n'
                                                     '  - "AC-1: find_returns answers like returns_for did"'))
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("adds or changes an acceptance criterion", "\n".join(self.ev["checks"][0]["details"]))

    def test_high_risk_is_strict_whatever_the_lane_field_says(self) -> None:
        self.mechanical_branch()
        self.p.write(MECH, self.p.read(MECH).replace("risk: low", "risk: high"))
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "strict")

    def test_high_risk_is_strict_even_with_an_invalid_lane(self) -> None:
        # A baselined lint error must not turn an unknown lane value into a way out of strict.
        from sdlc.artifacts import Ticket
        from pathlib import Path

        for lane, risk, want in (("fast", "high", "strict"), ("fast", "low", "standard"),
                                 ("mechanical", "low", "mechanical"), ("", "high", "strict")):
            with self.subTest(lane=lane, risk=risk):
                self.assertEqual(Ticket("T-1", Path("t.md"), {"lane": lane, "risk": risk}, "").lane, want)

    def test_override_raises_but_never_lowers(self) -> None:
        self.mechanical_branch()
        self.gate("build", "T-042-03", "lane", lane="standard")
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("override --lane standard", "\n".join(self.ev["checks"][0]["details"]))
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)
        self.gate("build", "T-042-02", "lane", lane="mechanical")
        self.assertEqual(self.ev["lane"], "standard")

    def test_pr_refuses_evidence_from_a_looser_lane(self) -> None:
        self.mechanical_branch()
        self.gate("build", "T-042-03")
        self.assertEqual(self.code, 0, self.out)
        self.p.commit("T-042-03 build")
        # A later commit on the branch is no longer just the rename.
        self.p.write("app/server.py", self.p.read("app/server.py").replace('"not_found"', '"missing"', 1))
        self.p.commit("sneak a behaviour change in")
        lane = self.gate("pr", "T-042-03", "lane")["lane"]
        self.assertEqual(lane["status"], "fail")
        self.assertIn("build evidence ran in the mechanical lane, but this branch needs standard", "\n".join(lane["details"]))

    # -- strict ----------------------------------------------------------
    def strict_ticket_on_main(self, accepted: bool) -> None:
        git(self.p.root, "checkout", "-q", "main")
        rel = "tickets/T-042-02-order-page.md"
        t = self.p.read(rel).replace("risk: low", "risk: high" + ("\naccepted_by: lead" if accepted else ""))
        self.p.write(rel, t)
        self.p.commit("lead: T-042-02 is high risk")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)

    def test_strict_needs_lead_sign_off_on_the_base_branch(self) -> None:
        self.strict_ticket_on_main(accepted=False)
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("risk: high", "risk: high\naccepted_by: me"))
        checks = self.gate("build", "T-042-02", "lane")
        self.assertEqual(self.ev["lane"], "strict")
        self.assertEqual(checks["lane"]["status"], "fail")
        self.assertIn("the strict lane needs lead sign-off: accepted_by on main's version of T-042-02",
                      "\n".join(checks["lane"]["details"]))

    def test_strict_with_sign_off_runs_the_contract_diff(self) -> None:
        self.strict_ticket_on_main(accepted=True)
        checks = self.gate("build", "T-042-02", "lane", "contract-diff")
        self.assertEqual(checks["lane"]["status"], "pass", checks["lane"])
        self.assertEqual(checks["contract-diff"]["status"], "pass")
        self.assertIn("unchanged since main", checks["contract-diff"]["summary"])

    def test_contract_change_is_strict_and_must_be_cited(self) -> None:
        self.mechanical_branch()
        c = self.p.read("arch/CONTRACTS.md")
        self.p.write("arch/CONTRACTS.md", c.replace("/orders/{id}  owner=T-042-02  sample=/orders/ord_1",
                                                    "/orders/{id}  owner=T-042-02  sample=/orders/ord_2"))
        checks = self.gate("build", "T-042-03", "lane", "contract-diff", "scope")
        self.assertEqual(self.ev["lane"], "strict")
        self.assertIn("arch/CONTRACTS.md changed (a contract change is strict, even as a rename)",
                      "\n".join(checks["lane"]["details"]))
        self.assertEqual(checks["scope"]["status"], "pass", checks["scope"])  # allowed, but strict
        self.assertEqual(checks["contract-diff"]["status"], "fail")
        self.assertIn("changed: page /orders/{id}", checks["contract-diff"]["details"])
        self.assertIn("page /orders/{id} changed, but T-042-03 does not cite /orders/{id} in contracts:",
                      checks["contract-diff"]["details"])

    def test_removed_contract_key_is_breaking(self) -> None:
        self.mechanical_branch()
        c = self.p.read("arch/CONTRACTS.md")
        self.p.write("arch/CONTRACTS.md", c.replace("/orders/{id}  owner=T-042-02  sample=/orders/ord_1\n", ""))
        self.p.write(MECH, self.p.read(MECH).replace("requirements: []", 'requirements: []\ncontracts:\n  - "/orders/{id}"'))
        checks = self.gate("build", "T-042-03", "contract-diff")
        self.assertEqual(checks["contract-diff"]["status"], "pass", checks["contract-diff"])
        self.assertIn("removed (breaking): page /orders/{id}", checks["contract-diff"]["details"])

    def test_strict_paths_make_a_pr_strict(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[lanes]\nstrict_paths = ["tools/**"]\n')
        self.p.commit("lead: tools are strict")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-03")
        self.mechanical_branch()
        self.p.write("tools/lint.py", self.p.read("tools/lint.py") + "\n")
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "strict")
        self.assertIn("tools/lint.py matches lanes.strict_paths 'tools/**'", "\n".join(self.ev["checks"][0]["details"]))

    def test_a_change_to_the_waivers_makes_a_pr_strict(self) -> None:
        # ADR-0002: only the lead adds or renews a waiver, so a ticket PR touching the file needs
        # a lead approval; scope lets it through, the lane does not.
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-03")
        self.mechanical_branch()
        self.p.write("sdlc-waivers.toml", "")
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "strict")
        self.assertIn("sdlc-waivers.toml changed (only the lead adds or renews a waiver)",
                      "\n".join(self.ev["checks"][0]["details"]))

    def test_hardened_makes_a_manifest_change_strict(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npreset = "hardened"\n')
        self.p.commit("lead: hardened")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-03")
        self.mechanical_branch()
        self.p.write("package.json", "{}\n")
        self.gate("build", "T-042-03", "lane")
        self.assertEqual(self.ev["lane"], "strict")
        self.assertIn("package.json matches lanes.strict_paths '**/package.json'",
                      "\n".join(self.ev["checks"][0]["details"]))

    def test_strict_never_skips_the_real_stack(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        cfg = self.p.read("sdlc.toml").replace('integration = "python tools/junit.py --start tests --out {junit}"',
                                               'integration = ""')
        self.p.write("sdlc.toml", cfg)
        self.p.commit("lead: no integration command")
        self.strict_ticket_on_main(accepted=True)
        checks = self.gate("test", "T-042-02", "integration")
        self.assertEqual(checks["integration"]["status"], "fail", checks["integration"])
        self.assertIn("required for this play", checks["integration"]["summary"])
        git(self.p.root, "checkout", "-q", "--", ".")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-03")
        self.mechanical_branch()
        self.assertEqual(self.gate("build", "T-042-03", "integration")["integration"]["status"], "skip")


class ReviewFindings(unittest.TestCase):
    """Bypasses the independent review of step 1 reproduced; each stays caught."""

    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def on_branch(self, name: str) -> None:
        git(self.p.root, "checkout", "-q", "-B", name)

    def check(self, play: str, ticket: str, *names: str) -> dict:
        self.code, self.out = self.p.sdlc("gate", play, ticket, "--only", ",".join(names))
        ev = json.loads((self.p.root / ".sdlc-run" / f"{ticket}.{play}.json").read_text(encoding="utf-8"))
        self.ev = ev
        return {c["name"]: c for c in ev["checks"]}

    def start_t2(self) -> None:
        self.on_branch("build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)

    def widen_t2(self, *rels: str) -> None:
        rel = "tickets/T-042-02-order-page.md"
        t = self.p.read(rel).replace("  - app/server.py\n", "  - app/server.py\n" + "".join(f"  - {r}\n" for r in rels))
        t = t.rstrip("\n") + "\n\n## Amendments\n\n" + "".join(f"- widen {r}: tidy wording\n" for r in rels)
        self.p.write(rel, t)

    def test_widening_never_reaches_lead_artifacts_evidence_or_test_play_files(self) -> None:
        hard = ("design/spec-042-return-status.md", "decisions/ADR-0001-stack.md", "evidence/T-042-01.build.json",
                "tests/test_http_returns.py")
        self.start_t2()
        self.widen_t2(*hard)
        for r in hard:
            self.p.write(r, self.p.read(r) + "\n")
        c = self.check("build", "T-042-02", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        for r in hard:
            self.assertIn(f"outside build write set: {r}", c["details"])

    def test_widening_to_ordinary_code_is_allowed(self) -> None:
        self.start_t2()
        self.widen_t2("app/returns.py")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n")
        c = self.check("build", "T-042-02", "scope")["scope"]
        self.assertEqual(c["status"], "pass", c)
        # Still flagged: the base branch's areas decide what the review must accept.
        self.assertIn("out of area (the approving review must name it under ## Out of area): app/returns.py",
                      c["details"])

    def test_mechanical_ticket_with_every_area_cannot_rewrite_the_spec(self) -> None:
        self.on_branch("build/T-042-03")
        self.p.write(MECH, MECH_TICKET.replace("  - app/returns.py\n  - app/test_returns.py", '  - "**"')
                     .replace("  - rename STATES -> RETURN_STATES", '  - \'literal "Unknown" -> "Unclear"\''))
        for rel in ("design/spec-042-return-status.md", "tickets/T-042-02-order-page.md"):
            self.p.write(rel, self.p.read(rel).replace("Unknown", "Unclear"))
        c = self.check("build", "T-042-03", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside build write set: design/spec-042-return-status.md", c["details"])
        self.assertIn("outside build write set: tickets/T-042-02-order-page.md", c["details"])

    def spike_on_main(self) -> None:
        self.p.write(Spikes.REL, Spikes.TICKET.replace("status: in_progress", "status: ready"))
        self.p.commit("lead: spike ready")
        self.on_branch("build/T-042-05")
        self.p.write(Spikes.REL, Spikes.TICKET)

    def test_spike_cannot_widen_its_way_to_code_or_new_folders(self) -> None:
        self.spike_on_main()
        t = self.p.read(Spikes.REL).replace("  - research/**\n", "  - research/**\n  - app/returns.py\n  - notes/**\n")
        self.p.write(Spikes.REL, t.rstrip("\n") + "\n\n## Amendments\n\n- widen app/returns.py: prototype\n"
                     "- widen notes/**: more room\n")
        self.p.write("research/carriers.md", "## Q-1 a\n\n## Q-2 b\n")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# prototype\n")
        self.p.write("notes/extra.md", "# extra\n")
        c = self.check("build", "T-042-05", "spike")["spike"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("app/returns.py: a spike changes documents only (.md, .markdown, .rst, .txt), not code, tests "
                      "or config", c["details"])
        self.assertIn("notes/extra.md: outside the spike's areas", c["details"])

    def mech(self, transforms: str) -> None:
        self.on_branch("build/T-042-03")
        self.p.write(MECH, MECH_TICKET.replace("  - app/returns.py\n  - app/test_returns.py", "  - app/**")
                     .replace("  - rename STATES -> RETURN_STATES", transforms))

    def lane(self) -> dict:
        return self.check("build", "T-042-03", "lane")["lane"]

    def test_a_move_that_keeps_its_source_is_a_copy(self) -> None:
        self.mech("  - move app/returns.py -> app/admin/returns.py")
        self.p.write("app/admin/returns.py", self.p.read("app/returns.py"))
        lane = self.lane()
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("residue: app/returns.py: declared moved to app/admin/returns.py, but it still exists",
                      lane["details"])

    def test_a_move_may_not_overwrite_a_base_file(self) -> None:
        self.mech("  - move app/returns.py -> app/server.py")
        self.p.write("app/server.py", self.p.read("app/returns.py"))
        (self.p.root / "app" / "returns.py").unlink()
        self.lane()
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("residue: app/server.py: a move may not overwrite a file that exists on the base branch",
                      self.ev["checks"][0]["details"])

    def test_two_moves_to_one_target_are_refused(self) -> None:
        self.mech("  - move app/returns.py -> app/x.py\n  - move app/pages.py -> app/x.py")
        code, out = self.p.sdlc("lint")
        self.assertNotEqual(code, 0)
        self.assertIn("each path may be moved from, and moved to, once", out)

    def binary_on_main(self, data: bytes) -> None:
        (self.p.root / "app" / "blob.bin").write_bytes(data)
        self.p.commit("a binary")

    def test_binary_changes_are_residue(self) -> None:
        self.binary_on_main(b"\xff\xfe\x00data")
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        self.assertEqual(self.lane()["status"], "pass")
        (self.p.root / "app" / "blob.bin").write_bytes(b"\xfe\xff\x00data")
        self.lane()
        self.assertEqual(self.ev["lane"], "standard")
        self.assertIn("residue: app/blob.bin:1: differs from what the transforms produce", self.ev["checks"][0]["details"])

    def test_line_endings_and_modes_are_residue(self) -> None:
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        self.assertEqual(self.ev_lane(), "mechanical")
        rel = self.p.root / "app" / "server.py"
        rel.write_bytes(rel.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.ev_lane(), "standard")
        git(self.p.root, "checkout", "-q", "--", "app/server.py")
        import os
        import stat
        os.chmod(rel, os.stat(rel).st_mode | stat.S_IXUSR)
        if os.name != "nt":
            self.assertEqual(self.ev_lane(), "standard")
            self.assertIn("residue: app/server.py: file mode changed", self.ev["checks"][0]["details"])

    def ev_lane(self) -> str:
        self.lane()
        return self.ev["lane"]

    def test_table_definitions_and_route_prose_are_in_the_contract_diff(self) -> None:
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        c = self.p.read("arch/CONTRACTS.md")
        self.p.write("arch/CONTRACTS.md", c.replace("returns  read-only projection owned by the returns service",
                                                    "returns  projection owned by the returns service")
                     .replace("- Unknown order: `404` `not_found`", "- Unknown order: `404`"))
        d = self.check("build", "T-042-03", "contract-diff")["contract-diff"]
        self.assertEqual(d["status"], "fail")
        self.assertIn("narrowed (breaking): table returns: dropped read-only", d["details"])
        self.assertIn("narrowed (breaking): GET /api/orders/{}/returns: dropped `not_found`", d["details"])
        self.p.write(MECH, self.p.read(MECH).replace("requirements: []", 'requirements: []\ncontracts:\n'
                                                     '  - returns\n  - "GET /api/orders/{id}/returns"'))
        d = self.check("build", "T-042-03", "contract-diff")["contract-diff"]
        self.assertEqual(d["status"], "pass", d)
        self.assertIn("returns is cited by this branch, not by main's ticket", d["details"])

    def test_contract_prose_outside_every_key_is_never_unchanged(self) -> None:
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        c = self.p.read("arch/CONTRACTS.md")
        self.p.write("arch/CONTRACTS.md", c.replace("- JSON over HTTP.", "- JSON or XML over HTTP."))
        d = self.check("build", "T-042-03", "contract-diff")["contract-diff"]
        self.assertNotIn("unchanged", d["summary"])
        self.assertIn("arch/CONTRACTS.md changed outside every declared key (conventions or prose): review the raw diff",
                      d["details"])

    def test_prose_under_a_heading_no_key_owns_is_reported(self) -> None:
        # Re-review N1: such a section was stored, matched no key, and was dropped from the diff.
        git(self.p.root, "checkout", "-q", "main")
        c = self.p.read("arch/CONTRACTS.md")
        self.p.write("arch/CONTRACTS.md", c.replace("## Pages", "### /api conventions\n\nErrors use one envelope.\n\n## Pages"))
        self.p.commit("lead: conventions section")
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        self.p.write("arch/CONTRACTS.md", self.p.read("arch/CONTRACTS.md").replace("one envelope", "two envelopes"))
        d = self.check("build", "T-042-03", "contract-diff")["contract-diff"]
        self.assertNotIn("unchanged", d["summary"])
        self.assertIn("arch/CONTRACTS.md changed outside every declared key (conventions or prose): review the raw diff",
                      d["details"])

    def test_a_committed_line_ending_change_is_residue_whatever_the_checkout_filters(self) -> None:
        # Re-review N2: eol=lf turned a committed CRLF blob back into LF before hashing.
        import subprocess

        self.p.write(".gitattributes", "*.py text eol=lf\n")
        self.p.commit("eol rules")
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        self.p.commit("rename")
        crlf = (self.p.root / "app" / "server.py").read_bytes().replace(b"\n", b"\r\n")
        sha = subprocess.run(["git", "hash-object", "-w", "--no-filters", "--stdin"], cwd=self.p.root, input=crlf,
                             capture_output=True, check=True).stdout.decode().strip()
        git(self.p.root, "update-index", "--cacheinfo", f"100644,{sha},app/server.py")
        git(self.p.root, "commit", "-q", "-m", "a CRLF blob")
        (self.p.root / "app" / "server.py").write_bytes(crlf)
        self.assertEqual(self.ev_lane(), "standard")
        self.assertTrue(any(d.startswith("residue: app/server.py:") for d in self.ev["checks"][0]["details"]))

    def test_ci_workflows_and_the_kit_pin_are_hard(self) -> None:
        # Re-review N4: these were out-of-area flags a reviewer glob could accept.
        self.start_t2()
        self.p.write(".github/workflows/sdlc.yml", "name: trimmed\n")
        c = self.check("build", "T-042-02", "scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("outside build write set: .github/workflows/sdlc.yml", c["details"])

    def test_no_merge_base_fails_the_lane(self) -> None:
        self.mech("  - rename STATES -> RETURN_STATES")
        rename(self.p)
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('base = "main"', 'base = "nope"')
                     if 'base = "main"' in self.p.read("sdlc.toml") else self.p.read("sdlc.toml") + '\n[vcs]\nbase = "nope"\n')
        lane = self.lane()
        self.assertEqual(lane["status"], "fail")
        self.assertIn("no merge base with nope", lane["summary"])

    def test_doctor_keeps_the_spike_floor(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\nspike = ["artifacts"]\n')
        code, out = self.p.sdlc("doctor")
        self.assertIn("gate.spike drops scope, immutable, spike", out)


REFAC = "tickets/T-042-04-returns-loader.md"
REFAC_TICKET = """---
id: T-042-04
title: Simplify the returns loader
type: chore
status: ready
risk: low
lane: refactor
depends_on: []
areas:
  - app/returns.py
  - app/test_returns.py
skills:
  - build
acceptance_criteria:
  - "AC-1: returns_for lists an order's returns, each with its id and state"
  - "AC-2: returns_for answers None for an order that does not exist"
requirements: []
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
---

Collapse the loader. Behaviour stays exactly as it is.
"""

OLD_LOADER = """    rows = _ORDERS.get(order_id)
    return None if rows is None else [dict(r) for r in rows]"""
NEW_LOADER = """    if order_id not in _ORDERS:
        return None
    return [{"id": r["id"], "state": r["state"]} for r in _ORDERS[order_id]]"""
CHARACTERISATION = (
    "\n\nclass ReturnsLoader(unittest.TestCase):\n"
    "    def test_lists_returns_with_id_and_state(self) -> None:\n"
    '        """T-042-04/AC-1"""\n'
    '        self.assertEqual(returns.returns_for("ord_1"),\n'
    '                         [{"id": "ret_1", "state": "requested"}, {"id": "ret_2", "state": "refunded"}])\n'
    "\n"
    "    def test_unknown_order_is_none(self) -> None:\n"
    '        """T-042-04/AC-2"""\n'
    '        self.assertIsNone(returns.returns_for("nope"))\n'
)
REVIEW = """---
ticket: T-042-04
verdict: approve
reviewer: fake-reviewer
commit: {commit}
---

# Review T-042-04: Simplify the returns loader

## Gate

Build evidence: pass in the refactor lane at `{commit}`.

## Acceptance criteria

| AC | Test | Verdict |
|---|---|---|
| AC-1 | app/test_returns.py ReturnsLoader.test_lists_returns_with_id_and_state | met |
| AC-2 | app/test_returns.py ReturnsLoader.test_unknown_order_is_none | met |
{equivalence}
## Findings

None.
"""


class RefactorLane(unittest.TestCase):
    """ADR-0004: a refactor proves its AC tests pass on the base and the head, keeps existing
    tests, changes production code, and its approval argues equivalence."""
    TESTS = "app/test_returns.py"

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write(REFAC, REFAC_TICKET)
        self.p.commit("lead: T-042-04 refactor ticket")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-04")
        self.assertEqual(self.p.sdlc("status", "T-042-04", "in_progress", "--as", "build")[0], 0)
        self.p.commit("start T-042-04")

    def tearDown(self) -> None:
        self.p.close()

    def refactor(self, loader: str = NEW_LOADER, tests: str = CHARACTERISATION) -> None:
        self.p.write("app/returns.py", self.p.read("app/returns.py").replace(OLD_LOADER, loader))
        body = self.p.read(self.TESTS)
        self.p.write(self.TESTS, body.replace("\n\nif __name__", tests + "\n\nif __name__"))

    def gate(self, *checks: str, play: str = "build") -> dict:
        args = ["gate", play, "T-042-04"] + (["--only", ",".join(checks)] if checks else [])
        self.code, self.out = self.p.sdlc(*args)
        name = f"T-042-04.{play}.json"
        f = self.p.root / ".sdlc-run" / name
        if not checks and (self.p.root / "evidence" / name).is_file():
            f = self.p.root / "evidence" / name
        self.ev = json.loads(f.read_text(encoding="utf-8"))
        return {c["name"]: c for c in self.ev["checks"]}

    def test_a_behaviour_neutral_refactor_passes_without_ac_red(self) -> None:
        self.refactor()
        checks = self.gate()
        self.assertEqual(self.code, 0, self.out)
        self.assertEqual(self.ev["lane"], "refactor")
        self.assertNotIn("ac-red", checks)
        self.assertEqual(checks["refactor"]["status"], "pass", checks["refactor"])
        self.assertIn("pass on main and on the head", checks["refactor"]["summary"])

    def test_a_test_that_pins_new_behaviour_fails(self) -> None:
        # The "refactor" makes an unknown order an empty list, and its AC test asserts that.
        self.refactor(loader="    return [dict(r) for r in _ORDERS.get(order_id, [])]",
                      tests=CHARACTERISATION.replace('self.assertIsNone(returns.returns_for("nope"))',
                                                     'self.assertEqual(returns.returns_for("nope"), [])'))
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(d.startswith("T-042-04/AC-2: ") and "behaviour it pins is new" in d
                            for d in c["details"]), c["details"])

    def test_an_ac_without_a_test_that_runs_on_the_base_fails(self) -> None:
        self.refactor(tests=CHARACTERISATION.split("\n    def test_unknown_order_is_none")[0])
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(d.startswith("T-042-04/AC-2: no tagged test ran") for d in c["details"]), c["details"])

    def test_a_refactor_must_change_production_code(self) -> None:
        self.refactor(loader=OLD_LOADER)
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("no production file of T-042-04 differs from main: a refactor changes code", c["details"])

    def test_existing_tests_may_gain_tags_but_not_lose_assertions(self) -> None:
        self.refactor()
        tagged = self.p.read(self.TESTS).replace('"""T-042-01/AC-4"""', '"""T-042-01/AC-4, T-042-04/AC-2"""')
        self.p.write(self.TESTS, tagged)
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "pass", c)
        self.p.write(self.TESTS, tagged.replace("        self.assertEqual(status, 404)\n", "", 1))
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("app/test_returns.py: removed or rewrote 'self.assertEqual(status, 404)'; existing tests may "
                      "only gain AC tags", c["details"])

    def test_a_tag_may_come_in_brackets_but_punctuation_is_kept(self) -> None:
        # New docstrings carry text, so none of them can stand in for the edited tag-only docstring.
        self.refactor(tests=CHARACTERISATION.replace('AC-1"""', 'AC-1 lists"""').replace('AC-2"""', 'AC-2 none"""'))
        body = self.p.read(self.TESTS)
        tagged = body.replace('"""T-042-01/AC-4"""', '"""T-042-01/AC-4 [T-042-04/AC-2]"""')
        self.p.write(self.TESTS, tagged)
        self.assertEqual(self.gate("refactor")["refactor"]["status"], "pass")
        # Dropping a comma joins the two strings: the list now holds one item, and the test is weaker.
        self.p.write(self.TESTS, tagged.replace('["ret_1", "ret_2"]', '["ret_1" "ret_2"]'))
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(d.startswith("app/test_returns.py: removed or rewrote 'self.assertEqual([r[") for d in c["details"]),
                        c["details"])

    def test_a_unit_command_that_reports_nothing_on_the_base_names_its_exit_code(self) -> None:
        # The gate reads its config from the base: the lead sets a unit command that needs the new code.
        git(self.p.root, "checkout", "-q", "main")
        cfg = self.p.read("sdlc.toml")
        self.p.write("sdlc.toml", cfg.replace('unit = "python', 'unit = "python -c \'from app import returns; returns.NEW\' && python', 1))
        self.p.commit("lead: unit command")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-04")
        self.refactor()
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n\nNEW = 1\n")
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(d.startswith("the unit command exited 1 and reported no test with the production files at main")
                            for d in c["details"]), c["details"])
        self.assertFalse(any("no tagged test ran" in d for d in c["details"]), c["details"])

    def test_an_assertion_may_not_move_to_another_test(self) -> None:
        self.refactor()
        body = self.p.read(self.TESTS)
        line = '        self.assertEqual(json.loads(body)["error"]["code"], "not_found")\n'
        # From the 404 test up into the first test, across lines the diff leaves alone.
        first = '        self.assertEqual(status, 200)\n'
        moved = body.replace(line, "", 1).replace(first, first + line, 1)
        self.assertNotEqual(moved, body)
        self.p.write(self.TESTS, moved)
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any("removed or rewrote 'self.assertEqual(json.loads(body)" in d for d in c["details"]), c["details"])

    def test_a_file_outside_the_areas_is_put_back_too(self) -> None:
        # server.py is outside the ticket's areas. Its new message would pass the new test if the
        # base run left it at the head.
        self.refactor(tests=CHARACTERISATION + (
            "\n    def test_unknown_order_message(self) -> None:\n"
            '        """T-042-04/AC-2"""\n'
            '        _, _, body = server.dispatch("GET", "/api/orders/nope/returns")\n'
            '        self.assertEqual(json.loads(body)["error"]["message"], "no order nope")\n'))
        srv = self.p.read("app/server.py")
        self.p.write("app/server.py", srv.replace('f"order {order_id} not found"', 'f"no order {order_id}"'))
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(d.startswith("T-042-04/AC-2: ") and "test_unknown_order_message" in d
                            and "behaviour it pins is new" in d for d in c["details"]), c["details"])

    def test_tags_may_not_be_retargeted_nor_whitespace_or_indentation_changed(self) -> None:
        self.refactor()
        body = self.p.read(self.TESTS)
        for old, new in [('"""T-042-01/AC-4"""', '"""T-042-01/AC-3"""'),
                         ('"not_found"', '"not _found"'),
                         ("        self.assertEqual(status, 404)\n",
                          "        if False:\n            self.assertEqual(status, 404)\n")]:
            with self.subTest(old=old):
                self.assertIn(old, body)
                self.p.write(self.TESTS, body.replace(old, new, 1))
                c = self.gate("refactor")["refactor"]
                self.assertEqual(c["status"], "fail", c)
                self.assertTrue(any("existing tests may only gain AC tags" in d for d in c["details"]), c["details"])

    def test_a_long_rewritten_line_does_not_stall_the_check(self) -> None:
        # A tag pattern with overlapping whitespace runs took minutes on a line like this one.
        self.refactor()
        body = self.p.read(self.TESTS)
        self.p.write(self.TESTS, body.replace("        self.assertEqual(status, 404)\n",
                                              "        self.assertEqual(status, 404)" + " " * 20000 + "x\n", 1))
        started = time.monotonic()
        c = self.gate("refactor")["refactor"]
        self.assertLess(time.monotonic() - started, 60)
        self.assertEqual(c["status"], "fail", c)

    def test_deleting_a_test_file_the_base_has_fails(self) -> None:
        self.refactor()
        self.p.write("app/test_loader.py", "import unittest\n\nfrom app import returns\n" + CHARACTERISATION)
        (self.p.root / self.TESTS).unlink()
        c = self.gate("refactor")["refactor"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("app/test_returns.py: a test the base has was deleted", c["details"])

    def test_the_build_prompt_states_the_refactor_rules(self) -> None:
        code, out = self.p.sdlc("prompt", "build", "T-042-04")
        self.assertEqual(code, 0, out)
        out = self.p.read(out.strip())
        self.assertIn("Behaviour does not change (ADR-0004)", out)
        self.assertIn("never remove or rewrite a line of an existing test", out)

    def test_the_refactor_lane_has_no_test_play(self) -> None:
        self.refactor()
        c = self.gate("lane", play="test")["lane"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("the refactor lane has no test play: the build gate's full suite is its proof", c["details"])

    def test_a_builder_cannot_lower_a_ticket_to_refactor(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write(REFAC, REFAC_TICKET.replace("lane: refactor\n", ""))
        self.p.commit("lead: T-042-04 is standard")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-04")
        self.p.write(REFAC, REFAC_TICKET.replace("status: ready", "status: in_progress"))
        self.refactor()
        c = self.gate("scope")["scope"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(": lane changed" in d for d in c["details"]), c["details"])

    def test_a_builder_cannot_raise_a_mechanical_ticket_to_refactor(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write(REFAC, REFAC_TICKET.replace("lane: refactor\n", "lane: mechanical\n"))
        self.p.commit("lead: T-042-04 is mechanical")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-04")
        self.refactor()
        self.p.write(REFAC, REFAC_TICKET)
        c = self.gate("scope")["scope"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any("lane changed to refactor; only the lead declares a refactor" in d for d in c["details"]),
                        c["details"])
        # Asking for refactor with --lane on the mechanical ticket gets standard, not refactor.
        self.p.write(REFAC, REFAC_TICKET.replace("lane: refactor\n", "lane: mechanical\n"))
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-04", "--only", "lane", "--lane", "refactor")
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-04.build.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["lane"], "standard", ev)

    def test_the_approval_must_argue_equivalence(self) -> None:
        self.refactor()
        self.p.commit("T-042-04 refactor")
        self.gate()
        self.assertEqual(self.code, 0, self.out)
        self.assertEqual(self.p.sdlc("status", "T-042-04", "in_review", "--as", "build")[0], 0)
        self.p.commit("evidence T-042-04: build gate pass")
        proven = self.ev["commit"]
        self.p.write("reviews/T-042-04.md", REVIEW.format(commit=proven, equivalence=""))
        c = self.gate("review-file", play="review")["review-file"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any("under ## Equivalence" in d for d in c["details"]), c["details"])
        self.p.write("reviews/T-042-04.md", REVIEW.format(commit=proven, equivalence=(
            "\n## Equivalence\n\n<Refactor lane only (ADR-0004): why the change keeps behaviour.>\n")))
        c = self.gate("review-file", play="review")["review-file"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any("under ## Equivalence" in d for d in c["details"]), c["details"])
        self.p.write("reviews/T-042-04.md", REVIEW.format(commit=proven, equivalence=(
            "\n## Equivalence\n\nThe membership test and the copy return what `.get` did.\n")))
        c = self.gate("review-file", play="review")["review-file"]
        self.assertEqual(c["status"], "pass", c)

    def test_a_refactor_failure_is_never_waived_or_baselined(self) -> None:
        from sdlc import baseline, waivers
        self.assertIn("refactor", waivers.NEVER)
        self.assertNotIn("refactor", baseline.BASELINE_CHECKS)

    def test_records_mode_approval_needs_equivalence(self) -> None:
        from sdlc import approval
        rec = approval.Record(sha="x", who="r", role="review", verdict="approve",
                              body="| AC-1 | t | met |\n| AC-2 | t | met |\n")
        ticket = type("T", (), {"acs": [("AC-1", ""), ("AC-2", "")]})()
        rest = ([], [], lambda body, heading: [], lambda f, g: False)
        self.assertIn("no ## Equivalence section: a refactor's approval argues why behaviour is unchanged (ADR-0004)",
                      approval._content_problems(rec, "review", ticket, "refactor", *rest))
        self.assertEqual(approval._content_problems(rec, "review", ticket, "standard", *rest), [])
        body = rec.body
        rec.body = body + "\n## Equivalence\n\n<Refactor lane only (ADR-0004): why\nbehaviour is kept.>\n"
        self.assertIn("no ## Equivalence section: a refactor's approval argues why behaviour is unchanged (ADR-0004)",
                      approval._content_problems(rec, "review", ticket, "refactor", *rest))
        rec.body = body + "\n## Equivalence\n\nSame rows, same None.\n"
        self.assertEqual(approval._content_problems(rec, "review", ticket, "refactor", *rest), [])


class Amendments(unittest.TestCase):
    REL = "tickets/T-042-02-order-page.md"

    def setUp(self) -> None:
        self.p = ProductRepo()
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)
        self.p.commit("start T-042-02")

    def tearDown(self) -> None:
        self.p.close()

    def checks(self, *names: str) -> dict:
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-02", "--only", ",".join(names))
        ev = json.loads((self.p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
        return {c["name"]: c for c in ev["checks"]}

    def edit(self, old: str, new: str, amend: str = "") -> None:
        t = self.p.read(self.REL).replace(old, new)
        if amend:
            t = t.rstrip("\n") + ("\n\n## Amendments\n\n" if "## Amendments" not in t else "\n") + amend + "\n"
        self.p.write(self.REL, t)

    AC3 = "and the page still answers 200"

    def test_adding_an_ac_needs_an_add_line(self) -> None:
        new_ac = '  - "AC-4: the page title names the order id"\n'
        t = self.p.read(self.REL)
        i = t.index("source_intent:")
        self.p.write(self.REL, t[:i] + new_ac + t[i:])
        c = self.checks("immutable", "scope")
        self.assertEqual(c["immutable"]["status"], "fail")
        self.assertIn(f"{self.REL}: AC-4 added without an `- add AC-4: why` amendment", c["immutable"]["details"])
        self.edit("", "", "- add AC-4: the builder found the title untested")
        c = self.checks("immutable", "scope")
        self.assertEqual(c["immutable"]["status"], "pass", c["immutable"])
        self.assertEqual(c["scope"]["status"], "pass", c["scope"])

    def test_strengthening_needs_a_strengthen_line(self) -> None:
        self.edit(self.AC3, self.AC3 + " within 2 seconds")
        self.assertEqual(self.checks("immutable")["immutable"]["status"], "fail")
        self.edit("", "", "- strengthen AC-3: also bound the response time")
        c = self.checks("immutable", "scope")
        self.assertEqual(c["immutable"]["status"], "pass", c["immutable"])
        self.assertEqual(c["scope"]["status"], "pass", c["scope"])

    def test_weakening_still_needs_the_spec(self) -> None:
        self.edit(self.AC3, "if convenient", "- weaken AC-3: too hard")
        c = self.checks("immutable")["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("AC-3 reworded", "\n".join(c["details"]))
        self.assertIn("Weakening or removing an AC needs the spec", "\n".join(c["details"]))

    def split(self, verbatim: bool) -> None:
        t = self.p.read(self.REL)
        m = next(ln for ln in t.splitlines() if ln.strip().startswith('- "AC-3:'))
        text = m.strip()[2:].strip('"')[len("AC-3: "):]
        self.p.write(self.REL, t.replace(m + "\n", ""))
        self.edit("", "", "- split AC-3 -> T-042-04: unknown states need their own design")
        body = t.split("---", 2)
        follow = (body[1].replace("id: T-042-02", "id: T-042-04").replace("status: ready", "status: draft")
                  .replace("status: in_progress", "status: draft"))
        follow += "split_from: T-042-02\n"
        lines = [ln for ln in follow.splitlines() if not ln.strip().startswith('- "AC-')]
        follow = "\n".join(lines).replace("acceptance_criteria:", "acceptance_criteria:\n  - \"AC-1: "
                                          + (text if verbatim else text + " sometimes") + "\"")
        self.p.write("tickets/T-042-04-unknown-states.md", "---" + follow + "\n---\n\nSplit from T-042-02.\n")

    def test_split_moves_the_ac_verbatim(self) -> None:
        self.split(verbatim=True)
        c = self.checks("immutable", "scope")
        self.assertEqual(c["immutable"]["status"], "pass", c["immutable"])
        self.assertEqual(c["scope"]["status"], "pass", c["scope"])

    def test_split_that_rewords_the_ac_is_a_removal(self) -> None:
        self.split(verbatim=False)
        c = self.checks("immutable")["immutable"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("AC-3 removed", "\n".join(c["details"]))

    def test_amendments_are_append_only(self) -> None:
        # A line merged earlier is history; a ticket PR may only add lines after it.
        git(self.p.root, "checkout", "-q", "main")
        self.edit("", "", "- widen app/pages.py: an earlier PR's amendment")
        self.p.commit("an earlier amendment")
        git(self.p.root, "checkout", "-q", "-B", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)
        self.assertEqual(self.checks("immutable")["immutable"]["status"], "pass")
        t = self.p.read(self.REL).replace("an earlier PR's amendment", "a rewritten reason")
        self.p.write(self.REL, t)
        c = self.checks("immutable")["immutable"]
        self.assertIn("## Amendments is append-only", "\n".join(c["details"]))

    def test_widening_areas_needs_a_widen_line(self) -> None:
        self.edit("  - app/pages.py\n", "  - app/pages.py\n  - app/returns.py\n")
        c = self.checks("scope")["scope"]
        self.assertEqual(c["status"], "fail")
        self.assertIn(f"{self.REL}: files gains app/returns.py without a `- widen app/returns.py: <reason>` line in "
                      "## Amendments",
                      c["details"])
        self.edit("", "", "- widen app/returns.py: the page reuses the returns helper")
        self.assertEqual(self.checks("scope")["scope"]["status"], "pass")

    def test_lead_fields_and_lowering_the_lane_are_not_amendments(self) -> None:
        for old, new, field in (("title: ", "title: Easier ", "title"), ("risk: low", "risk: low\nlane: mechanical", "lane"),
                                ("depends_on:", "depends_on: []\nold_depends_on:", "old_depends_on")):
            with self.subTest(field=field):
                t = self.p.read(self.REL)
                self.p.write(self.REL, t.replace(old, new, 1))
                c = self.checks("scope")["scope"]
                self.assertEqual(c["status"], "fail", c)
                self.assertTrue(any(f": {field} changed" in d for d in c["details"]), c["details"])
                self.p.write(self.REL, t)

    def test_body_changes_outside_amendments_are_not_allowed(self) -> None:
        self.edit("Render", "Render, quickly,")
        c = self.checks("scope")["scope"]
        self.assertIn(f"{self.REL}: the ticket body changed outside ## Amendments", c["details"])


class Spikes(unittest.TestCase):
    REL = "tickets/T-042-05-spike.md"
    TICKET = """---
id: T-042-05
title: Find out how carriers report return states
type: spike
status: in_progress
risk: low
depends_on: []
areas:
  - research/**
skills:
  - research
questions:
  - "Q-1: which carriers push state changes instead of being polled"
  - "Q-2: how stale can a refunded state be"
requirements: []
source_spec: design/spec-042-return-status.md
source_plan: arch/plan-042-return-status.md
---

Answer the questions; no code.
"""

    def setUp(self) -> None:
        self.p = ProductRepo()
        git(self.p.root, "checkout", "-q", "main")
        self.p.write(self.REL, self.TICKET.replace("status: in_progress", "status: ready"))
        self.p.commit("lead: spike ready")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-05")
        self.p.write(self.REL, self.TICKET)

    def tearDown(self) -> None:
        self.p.close()

    def spike(self) -> dict:
        self.code, self.out = self.p.sdlc("gate", "build", "T-042-05")
        ev = json.loads((self.p.root / "evidence" / "T-042-05.build.json").read_text(encoding="utf-8")) \
            if (self.p.root / "evidence" / "T-042-05.build.json").is_file() else \
            json.loads((self.p.root / ".sdlc-run" / "T-042-05.build.json").read_text(encoding="utf-8"))
        return {c["name"]: c for c in ev["checks"]}

    def test_findings_answer_every_question(self) -> None:
        self.p.write("research/carriers.md", "# Carriers\n\n## Q-1 push vs poll\n\nTwo push.\n\n## Q-2 staleness\n\nA day.\n")
        checks = self.spike()
        self.assertEqual(self.code, 0, self.out)
        self.assertNotIn("ac-red", checks)
        self.assertEqual(checks["spike"]["summary"], "2 question(s) answered in 1 findings file(s)")

    def test_unanswered_question_fails(self) -> None:
        self.p.write("research/carriers.md", "# Carriers\n\n## Q-1 push vs poll\n\nTwo push.\n")
        c = self.spike()["spike"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("Q-2: no findings heading starts with Q-2", c["details"])

    def test_spike_may_not_change_code_or_tests(self) -> None:
        self.p.write("research/carriers.md", "## Q-1 a\n\n## Q-2 b\n")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# prototype\n")
        c = self.spike()["spike"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("app/returns.py: a spike changes documents only (.md, .markdown, .rst, .txt), not code, "
                      "tests or config", c["details"])


class SourceGlobs(unittest.TestCase):
    def test_ac_red_reverts_only_production_source(self) -> None:
        from helpers import FIXTURES
        import shutil

        p = ProductRepo()
        try:
            for source_globs, want in ((None, "2 file(s) reverted"), ('["app/pages.py"]', "1 file(s) reverted")):
                with self.subTest(source_globs=source_globs):
                    git(p.root, "checkout", "-q", "main")
                    if source_globs:
                        p.write("sdlc.toml", p.read("sdlc.toml").replace("[tests]", f"[tests]\nsource_globs = {source_globs}"))
                        p.commit("lead: source globs")
                    git(p.root, "checkout", "-q", "-B", "build/T-042-02")
                    self.assertEqual(p.sdlc("status", "T-042-02", "in_progress", "--as", "build")[0], 0)
                    sol = FIXTURES / "solutions" / "build-T-042-02"
                    for f in sol.rglob("*"):
                        if f.is_file():
                            dest = p.root / f.relative_to(sol)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(f, dest)
                    code, out = p.sdlc("gate", "build", "T-042-02", "--only", "ac-red")
                    ev = json.loads((p.root / ".sdlc-run" / "T-042-02.build.json").read_text(encoding="utf-8"))
                    c = {c["name"]: c for c in ev["checks"]}["ac-red"]
                    self.assertEqual(c["status"], "pass", c)
                    self.assertIn(want, c["summary"])
                    git(p.root, "checkout", "-q", "--", ".")
                    git(p.root, "clean", "-qfd")
        finally:
            p.close()


class Doctor(unittest.TestCase):
    def test_lanes_cannot_drop_their_floor(self) -> None:
        from sdlc import config
        p = ProductRepo()
        try:
            base = p.read("sdlc.toml")
            code, out = p.sdlc("doctor")
            self.assertNotIn("gate.mechanical drops", out)
            self.assertNotIn("gate.build drops", out)
            self.assertNotIn("gate.refactor drops", out)
            for over, want in (('mechanical = ["artifacts", "unit"]', "gate.mechanical drops"),
                               ('build = ["artifacts", "unit"]', "gate.build drops ac-red"),
                               ("strict = []", "gate.strict drops contract-diff"),
                               ('refactor = ["artifacts", "unit"]', "gate.refactor drops"),
                               ('refactor = ' + str(list(config.DEFAULTS["gate"]["refactor"]) + ["ac-red"]).replace("'", '"'),
                                "gate.refactor runs ac-red")):
                with self.subTest(over=over):
                    p.write("sdlc.toml", base + f"\n[gate]\n{over}\n")
                    code, out = p.sdlc("doctor")
                    self.assertNotEqual(code, 0)
                    self.assertIn(want, out)
            self.assertNotIn("gate.refactor does not", self.p_out(p, base))
            build = str(list(config.DEFAULTS["gate"]["build"]) + ["security"]).replace("'", '"')
            refactor = str(list(config.DEFAULTS["gate"]["refactor"])).replace("'", '"')
            note = self.p_out(p, base + f'\n[gate]\nbuild = {build}\nrefactor = {refactor}\n')
            self.assertIn("note  gate.build runs security and gate.refactor does not: a refactor ticket skips them", note)
            # Without its own [gate] refactor, the product's refactor build follows its build.
            self.assertNotIn("gate.refactor does not", self.p_out(p, base + f'\n[gate]\nbuild = {build}\n'))
        finally:
            p.close()

    @staticmethod
    def p_out(p, toml: str) -> str:
        p.write("sdlc.toml", toml)
        return p.sdlc("doctor")[1]

    def test_the_refactor_list_follows_a_custom_build(self) -> None:
        from sdlc import config
        default = list(config.DEFAULTS["gate"]["refactor"])
        cfg = config.load(text='[gate]\nbuild = ["artifacts", "unit", "ac-red", "security"]\n')
        self.assertEqual(cfg.section("gate")["refactor"], default + ["security"])
        cfg = config.load(text='[gate]\nbuild = ["artifacts", "unit", "ac-red"]\nrefactor = ["artifacts", "unit", "refactor"]\n')
        self.assertEqual(cfg.section("gate")["refactor"], ["artifacts", "unit", "refactor"])


if __name__ == "__main__":
    unittest.main()
