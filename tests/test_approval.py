"""ADR-0001 step 2: approvals bound to the PR's own diff, evidence in CI, status derived from git.
Each new check has a test that catches the defect it exists for and one showing the reference
passes. The forge is faked: CI never touches the network."""
import json
import shutil
import unittest

from helpers import FIXTURES, ProductRepo, git

from sdlc import approval, gitutil

REVIEW = (FIXTURES / "solutions" / "review-T-042-02" / "reviews" / "T-042-02.md").read_text(encoding="utf-8")
REVIEW_BODY = REVIEW.split("---", 2)[2]
RECORDS = """
[approval]
mode = "forge"
reviewers = ["rev"]
leads = ["lead"]
bots = ["bot"]
repo = "owner/product"
"""


class FakeGitHub:
    """The forge API calls approval.py makes, answered from memory."""

    def __init__(self, n: int, author: str, head: str):
        self.n, self.pr = n, {"user": {"login": author}, "head": {"sha": head}, "base": {"ref": "main"}}
        self.reviews, self.comments, self.commits, self.posted = [], [], [{"author": {"login": author}}], []
        self.permissions = {"rev": "write", "lead": "admin", "bot": "write", "ahmed": "admin", "builder-bot": "write"}

    def get(self, path: str):
        if path.startswith("/collaborators/"):
            return {"permission": self.permissions.get(path.split("/")[2], "read")}
        assert path == f"/pulls/{self.n}", path
        return self.pr

    def pages(self, path: str):
        return {f"/pulls/{self.n}/reviews": self.reviews, f"/issues/{self.n}/comments": self.comments,
                f"/pulls/{self.n}/commits": self.commits}[path]

    def post(self, path: str, data: dict):
        self.posted.append((path, data))
        return {"html_url": f"https://example.invalid/{len(self.posted)}"}


def copy_solution(p: ProductRepo, name: str) -> None:
    sol = FIXTURES / "solutions" / name
    for f in sol.rglob("*"):
        if f.is_file():
            dest = p.root / f.relative_to(sol)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)


def commit(p: ProductRepo, msg: str, ticket: str = "T-042-02", agent: str = "builder", play: str = "build") -> str:
    git(p.root, "add", "-A")
    git(p.root, "commit", "-q", "-m", msg, "-m", f"Sdlc-Agent: {agent}\nSdlc-Play: {play}\nSdlc-Ticket: {ticket}")
    return git(p.root, "rev-parse", "HEAD").strip()


class Base(unittest.TestCase):
    extra = ""

    def setUp(self) -> None:
        self.p = ProductRepo()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + RECORDS + self.extra)
        self.p.commit("lead: approvals outside the tree")
        self._client = approval.forge_client
        self.fake = None
        approval.forge_client = lambda cfg: self.fake

    def tearDown(self) -> None:
        approval.forge_client = self._client
        self.p.close()

    def build(self) -> str:
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        return commit(self.p, "T-042-02: order page returns section")

    def forge(self, author: str = "builder-bot") -> FakeGitHub:
        self.fake = FakeGitHub(7, author, git(self.p.root, "rev-parse", "HEAD").strip())
        return self.fake

    def record(self, who: str, sha: str, verdict: str = "approve", role: str = "review", agent: str = "reviewer",
               body: str = REVIEW_BODY, association: str = "COLLABORATOR", at: str = "2026-10-04T10:00:00Z",
               ticket: str = "T-042-02") -> None:
        self.fake.comments.append({"user": {"login": who}, "author_association": association, "created_at": at,
                                   "body": approval.render(ticket, sha, verdict, role, agent, body)})

    def approval(self, *extra: str) -> tuple[int, str, dict]:
        code, out = self.p.sdlc("approval", "--pr", "7", "--base", "main", *extra)
        f = self.p.root / ".sdlc-run" / "approval.json"
        return code, out, (json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {})


class Coverage(Base):
    """An approval covers the head when the PR's own change is the same, location-exact."""

    def setUp(self) -> None:
        super().setUp()
        self.reviewed = self.build()

    def covers(self) -> list[str]:
        return gitutil.covers(self.p.root, "main", self.reviewed, "HEAD")

    def merge_main_with(self, rel: str, edit) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write(rel, edit(self.p.read(rel)))
        self.p.commit(f"main edits {rel}")
        git(self.p.root, "checkout", "-q", "build/T-042-02")
        git(self.p.root, "merge", "-q", "--no-edit", "main")

    def test_the_reviewed_head_is_covered(self) -> None:
        self.assertEqual(self.covers(), [])

    def test_a_base_merge_keeps_the_approval(self) -> None:
        self.merge_main_with("tools/lint.py", lambda t: t + "\n# unrelated\n")
        self.merge_main_with("app/server.py", lambda t: "# main's header line\n" + t)  # same file, other hunk
        self.assertEqual(self.covers(), [])

    def test_editing_an_approved_line_voids_it(self) -> None:
        self.p.write("app/pages.py", self.p.read("app/pages.py").replace("Unknown", "Unclear", 1))
        commit(self.p, "after review")
        self.assertTrue(any(x.startswith("app/pages.py:") for x in self.covers()), self.covers())

    def test_moving_an_approved_line_voids_it(self) -> None:
        # The bypass a content-only fingerprint would allow: same lines, different place.
        lines = self.p.read("app/pages.py").split("\n")
        moved = lines[-3:] + lines[:-3]
        self.p.write("app/pages.py", "\n".join(moved))
        commit(self.p, "reorder after review")
        self.assertIn("app/pages.py: differs from the reviewed version beyond the base branch's change", self.covers())

    def test_a_new_file_voids_it(self) -> None:
        self.p.write("app/extra.py", "X = 1\n")
        commit(self.p, "more after review")
        self.assertIn("app/extra.py: changed after the review", self.covers())

    def test_an_unknown_reviewed_commit_covers_nothing(self) -> None:
        self.assertEqual(gitutil.covers(self.p.root, "main", "0" * 40, "HEAD"),
                         [f"reviewed commit {'0' * 12} is not in this repository's history"])


class Identity(Base):
    def setUp(self) -> None:
        super().setUp()
        self.head = self.build()
        self.forge()

    def test_an_independent_reviewer_approves(self) -> None:
        self.record("rev", self.head)
        code, out, res = self.approval()
        self.assertEqual(code, 0, out)
        self.assertIn("T-042-02 (standard) approved", res["summary"])
        self.assertFalse(res["trust_based"])

    def test_no_record_is_no_approval(self) -> None:
        code, out, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("needs an approval from an independent reviewer", res["summary"])

    def test_identities_outside_the_allowlist_do_not_count(self) -> None:
        self.record("stranger", self.head)
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("stranger is not in [approval] reviewers", "\n".join(res["details"]))

    def test_the_pr_author_cannot_approve(self) -> None:
        self.fake.pr["user"]["login"] = "rev"
        self.record("rev", self.head)
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("rev opened this PR", "\n".join(res["details"]))

    def test_a_commit_author_cannot_approve(self) -> None:
        self.fake.commits.append({"author": {"login": "rev"}})
        self.record("rev", self.head)
        self.assertIn("rev authored commits in this PR", "\n".join(self.approval()[2]["details"]))

    def test_the_building_agent_cannot_review(self) -> None:
        self.record("rev", self.head, agent="builder")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("reviewer builder also built this change", "\n".join(res["details"]))

    def test_a_later_request_changes_withdraws_the_approval(self) -> None:
        self.record("rev", self.head, at="2026-10-04T10:00:00Z")
        self.record("rev", self.head, verdict="request_changes", at="2026-10-04T11:00:00Z")
        self.assertNotEqual(self.approval()[0], 0)

    def test_a_stale_approval_does_not_count(self) -> None:
        self.record("rev", self.head)
        self.p.write("app/pages.py", self.p.read("app/pages.py").replace("Unknown", "Unclear", 1))
        commit(self.p, "after review")
        self.fake.pr["head"]["sha"] = git(self.p.root, "rev-parse", "HEAD").strip()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("app/pages.py", "\n".join(res["details"]))

    def test_the_review_must_cover_every_ac(self) -> None:
        body = "\n".join(ln for ln in REVIEW_BODY.split("\n") if not ln.startswith("| AC-3"))
        self.record("rev", self.head, body=body)
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("no AC row for AC-3", "\n".join(res["details"]))

    def test_a_native_forge_approval_counts_by_allowlist_role(self) -> None:
        self.fake.reviews.append({"user": {"login": "rev"}, "author_association": "COLLABORATOR", "state": "APPROVED",
                                  "commit_id": self.head, "body": REVIEW_BODY, "submitted_at": "2026-10-04T10:00:00Z"})
        self.assertEqual(self.approval()[0], 0)

    def test_a_pr_cannot_switch_its_own_approval_mode(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('mode = "forge"', 'mode = "file"'))
        commit(self.p, "turn approvals off")
        self.fake.pr["head"]["sha"] = git(self.p.root, "rev-parse", "HEAD").strip()
        code, out, res = self.approval()
        self.assertNotEqual(code, 0, out)
        self.assertIn("needs an approval", res["summary"])


class LeadPRs(Base):
    def test_a_pr_without_a_ticket_needs_the_lead_even_for_lead_artifacts(self) -> None:
        # Review of step 2: config, CI and the kit pin are lead artifacts that govern every
        # later PR; a builder's ticketless PR adding itself to `leads` passed with no approval.
        git(self.p.root, "checkout", "-q", "-b", "lead/config")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('leads = ["lead"]', 'leads = ["lead", "builder-bot"]'))
        self.p.commit("add myself to leads")
        self.forge()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("this PR (lead PR) needs a lead approval", res["summary"])
        self.record("lead", git(self.p.root, "rev-parse", "HEAD").strip(), role="lead", agent="", body="ok", ticket="")
        self.assertEqual(self.approval()[0], 0)

    def test_code_without_a_ticket_needs_the_lead(self) -> None:
        # A forgotten Sdlc-Ticket trailer must not turn a code change into an unapproved lead PR.
        git(self.p.root, "checkout", "-q", "-b", "hotfix")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# hotfix\n")
        self.p.commit("hotfix without a ticket")
        self.forge()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("this PR (lead PR) needs a lead approval (for a PR without a ticket (1 file(s)))", res["summary"])
        self.record("lead", git(self.p.root, "rev-parse", "HEAD").strip(), role="lead", agent="", body="ok",
                    ticket="")
        self.assertEqual(self.approval()[0], 0)


class Strict(Base):
    def test_strict_needs_a_lead_on_top_of_the_review(self) -> None:
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("risk: low", "risk: high"))
        self.p.commit("lead: high risk")
        head = self.build()
        self.forge()
        self.record("rev", head)
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("T-042-02 (strict) needs a lead approval (strict lane)", res["summary"])
        self.record("lead", head, role="lead", agent="", body="Signed off.")
        self.assertEqual(self.approval()[0], 0)

    def test_weakening_an_ac_needs_a_lead(self) -> None:
        head = self.build()
        rel = "tickets/T-042-02-order-page.md"
        t = self.p.read(rel).replace("and the page still answers 200", "if convenient")
        self.p.write(rel, t.rstrip("\n") + "\n\n## Amendments\n\n- weaken AC-3: the 200 is out of scope\n")
        head = commit(self.p, "weaken AC-3")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertEqual(code, 0, out)  # allowed by immutable once approvals carry the decision
        self.assertIn("AC-3 weakened by amendment: needs a lead approval", out + self.p.read(".sdlc-run/ci.json"))
        self.forge()
        body = REVIEW_BODY + "\n## Amendments\n\n- `AC-3`: agreed\n"
        self.record("rev", head, body=body)
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("a lead approval (for T-042-02: weaken AC-3)", res["summary"])
        self.record("lead", head, role="lead", agent="", body="Yes, drop the 200.")
        self.assertEqual(self.approval()[0], 0)


class ReviewFindings(Base):
    """Bypasses the independent review of step 2 found; each stays caught."""

    def setUp(self) -> None:
        super().setUp()
        self.head = self.build()
        self.forge()

    def test_a_merge_that_undoes_the_bases_change_voids_the_approval(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("app/server.py", self.p.read("app/server.py").replace('"not_found"', '"missing"', 1))
        self.p.commit("main: rename an error code")
        git(self.p.root, "checkout", "-q", "build/T-042-02")
        git(self.p.root, "merge", "-q", "-s", "ours", "--no-edit", "main")  # keeps the PR's side: reverts main
        self.assertIn("app/server.py: differs from the reviewed version beyond the base branch's change",
                      gitutil.covers(self.p.root, "main", self.head, "HEAD"))

    def test_a_ticketless_weakening_needs_a_lead(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "weaken", "main")
        rel = "tickets/T-042-02-order-page.md"
        t = self.p.read(rel).replace("and the page still answers 200", "if convenient")
        self.p.write(rel, t.rstrip("\n") + "\n\n## Amendments\n\n- weaken AC-3: meh\n")
        self.p.commit("weaken without a ticket")
        code, out = self.p.sdlc("gate", "ci", "--only", "immutable", "--base", "main")
        self.assertIn("AC weakened or removed by amendment: allowed only with a lead approval", out)
        self.forge()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("T-042-02: weaken AC-3", res["summary"])

    def review(self, state: str, commit_id: str, body: str, at: str = "2026-10-04T10:00:00Z", who: str = "rev") -> None:
        self.fake.reviews.append({"user": {"login": who}, "author_association": "COLLABORATOR", "state": state,
                                  "commit_id": commit_id, "body": body, "submitted_at": at})

    def test_a_review_is_bound_to_the_commit_the_forge_recorded(self) -> None:
        old = git(self.p.root, "rev-parse", "HEAD~1").strip()
        rec = approval.render("T-042-02", self.head, "approve", "review", "reviewer", REVIEW_BODY)
        self.review("APPROVED", old, rec)  # given on an older commit, body names the head
        self.assertNotEqual(self.approval()[0], 0)
        self.fake.reviews.clear()
        self.review("COMMENTED", self.head, rec)  # a comment-only review is no verdict
        self.assertNotEqual(self.approval()[0], 0)
        self.fake.reviews.clear()
        self.review("APPROVED", self.head, rec)
        self.assertEqual(self.approval()[0], 0)

    def test_dismissed_and_contradicting_reviews_approve_nothing(self) -> None:
        rec = approval.render("T-042-02", self.head, "approve", "review", "reviewer", REVIEW_BODY)
        self.review("DISMISSED", self.head, rec)
        self.assertNotEqual(self.approval()[0], 0)
        self.fake.reviews.clear()
        self.review("CHANGES_REQUESTED", self.head, rec)
        self.assertNotEqual(self.approval()[0], 0)

    def test_an_edited_comment_approves_nothing(self) -> None:
        self.record("rev", self.head)
        self.fake.comments[-1]["updated_at"] = "2026-10-04T12:00:00Z"
        self.assertNotEqual(self.approval()[0], 0)
        self.fake.comments[-1]["updated_at"] = self.fake.comments[-1]["created_at"]
        self.assertEqual(self.approval()[0], 0)

    def test_a_later_approval_supersedes_the_same_reviewers_native_changes_request(self) -> None:
        self.review("CHANGES_REQUESTED", self.head, "please fix", at="2026-10-04T09:00:00Z")
        self.record("rev", self.head, at="2026-10-04T10:00:00Z")
        code, out, res = self.approval()
        self.assertEqual(code, 0, res)

    def test_one_identity_cannot_be_reviewer_and_lead_at_once(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("risk: low", "risk: high"))
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('leads = ["lead"]', 'leads = ["lead", "rev"]'))
        self.p.commit("lead: high risk; rev also leads")
        git(self.p.root, "checkout", "-q", "build/T-042-02")
        git(self.p.root, "merge", "-q", "--no-edit", "main")
        self.forge()
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.record("rev", head)
        self.record("rev", head, role="lead", agent="", body="also lead", at="2026-10-04T10:01:00Z")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("the review and the lead approval from different identities", res["summary"])
        self.record("lead", head, role="lead", agent="", body="ok", at="2026-10-04T10:02:00Z")
        self.assertEqual(self.approval()[0], 0)

    def test_the_pr_gate_keeps_checks_the_lead_added(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[gate]\npr = ["artifacts", "scope", "immutable", "skills"]\n')
        self.p.commit("lead: skills in the PR gate")
        git(self.p.root, "checkout", "-q", "build/T-042-02")
        git(self.p.root, "merge", "-q", "--no-edit", "main")
        self.p.sdlc("gate", "pr", "--base", "main")
        names = [c["name"] for c in json.loads(self.p.read(".sdlc-run/T-042-02.pr.json"))["checks"]]
        self.assertIn("skills", names)

    def test_trace_trusts_only_this_commits_ci_evidence(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("gate", "ci")[0], 0)
        self.p.write("README.md", self.p.read("README.md") + "\n")
        self.p.commit("a later commit")
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0)  # the old ci.json proves an older commit
        self.assertIn("T-042-02: done without passing build evidence", out)

    def test_a_comment_event_reads_the_base_branch_from_the_pr(self) -> None:
        git(self.p.root, "update-ref", "refs/remotes/origin/main", "main")
        self.record("rev", self.head)
        code, out = self.p.sdlc("approval", "--pr", "7")  # no --base: an issue_comment event has none
        self.assertEqual(code, 0, out)

    def test_the_result_is_posted_on_the_pr_head(self) -> None:
        self.record("rev", self.head)
        self.approval("--publish-status")
        path, data = self.fake.posted[-1]
        self.assertEqual(path, f"/statuses/{self.head}")
        self.assertEqual((data["state"], data["context"]), ("success", "sdlc/approval"))


class GitIdentity(Base):
    def test_allowed_signers_come_from_the_base_branch(self) -> None:
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("signers", "lead ssh-ed25519 AAAA-the-real-lead\n")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + 'allowed_signers = "signers"\n')
        self.p.commit("lead: signers")
        git(self.p.root, "checkout", "-q", "-b", "sneaky")
        self.p.write("signers", "lead ssh-ed25519 AAAA-the-builders-key\n")
        self.p.commit("swap the lead's key")
        cfg = __import__("sdlc.config", fromlist=["load"]).load(self.p.root)
        with open(approval.signers_file(cfg, "main"), encoding="utf-8") as f:
            self.assertIn("the-real-lead", f.read())

    def test_a_signer_who_committed_cannot_approve(self) -> None:
        cfg = __import__("sdlc.config", fromlist=["load"]).load(self.p.root)
        rec = approval.Record(sha="x", who="lead@example.com", role="lead", verdict="approve", source="note", signed=True)
        cfg.data["approval"]["leads"] = ["lead@example.com"]
        self.assertIn("signer lead@example.com authored or committed this PR's commits",
                      approval.identity_problems(cfg, rec, "lead", None, set(), {"lead@example.com"}))
        self.assertEqual(approval.identity_problems(cfg, rec, "lead", None, set(), {"builder@example.com"}), [])


class Trust(Base):
    extra = "trust_unsigned = true\n"

    def setUp(self) -> None:
        super().setUp()
        self.head = self.build()
        self.forge(author="ahmed")

    def test_one_identity_can_approve_and_says_so(self) -> None:
        self.record("ahmed", self.head, association="OWNER")
        code, out, res = self.approval()
        self.assertEqual(code, 0, out)
        self.assertTrue(res["trust_based"])
        self.assertTrue(res["summary"].startswith("[trust-based: identities not verified] "), res["summary"])

    def test_trust_still_needs_write_access(self) -> None:
        # On a public repository anyone can comment an approval record; and author_association
        # says nothing about permission (a read-only org member is MEMBER): the permission is asked.
        self.record("passer-by", self.head, association="NONE")
        self.record("member", self.head, association="MEMBER")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        details = "\n".join(res["details"])
        self.assertIn("passer-by has no write access (read)", details)
        self.assertIn("member has no write access (read)", details)

    def test_trust_still_needs_a_different_agent(self) -> None:
        self.record("ahmed", self.head, association="OWNER", agent="builder")
        self.assertNotEqual(self.approval()[0], 0)


class GitNotes(Base):
    extra = ""

    def setUp(self) -> None:
        super().setUp()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('mode = "forge"', 'mode = "git"'))
        self.p.commit("lead: notes")
        self.head = self.build()

    def note(self) -> None:
        f = self.p.root / ".sdlc-run" / "review-T-042-02.md"
        f.parent.mkdir(exist_ok=True)
        f.write_text(approval.render("T-042-02", self.head, "approve", "review", "reviewer", REVIEW_BODY),
                     encoding="utf-8")
        code, out = self.p.sdlc("review", "publish", "T-042-02")
        self.assertEqual(code, 0, out)

    def test_missing_notes_fail_closed(self) -> None:
        code, out, _ = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("refs/notes/sdlc is missing", out)

    def test_an_unsigned_note_does_not_count(self) -> None:
        self.note()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("unsigned note", "\n".join(res["details"]))

    def test_an_unsigned_note_counts_when_the_lead_accepts_trust(self) -> None:
        self.note()
        git(self.p.root, "checkout", "-q", "main")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + "trust_unsigned = true\n")
        self.p.commit("lead: trust-based")
        git(self.p.root, "checkout", "-q", "build/T-042-02")
        git(self.p.root, "merge", "-q", "--no-edit", "main")
        code, out, res = self.approval()
        self.assertEqual(code, 0, out)
        self.assertTrue(res["trust_based"])


class DerivedStatus(Base):
    def test_merged_trailer_makes_a_ticket_done(self) -> None:
        self.build()
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "ready")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("next")
        self.assertNotIn("T-042-02", out)

    def test_delivery_statuses_are_not_stored(self) -> None:
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertNotEqual(code, 0)
        self.assertIn("in_progress is derived, not stored", out)
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("status: ready", "status: in_progress"))
        code, out = self.p.sdlc("lint")
        self.assertIn("status in_progress is derived, not stored", out)

    def test_build_gate_needs_no_status_move_and_commits_no_evidence(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        code, out = self.p.sdlc("gate", "build", "T-042-02")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.p.root / "evidence" / "T-042-02.build.json").exists())
        self.assertTrue((self.p.root / ".sdlc-run" / "T-042-02.build.json").is_file())

    def test_pr_gate_finds_its_ticket_by_trailer_and_proves_it_on_the_head(self) -> None:
        self.build()
        code, out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertEqual(code, 0, out)
        self.assertIn("gate pr: ticket T-042-02", out)
        ev = json.loads(self.p.read(".sdlc-run/T-042-02.pr.json"))
        names = [c["name"] for c in ev["checks"]]
        for want in ("ac-red", "integration", "ac-coverage", "scope", "immutable"):
            self.assertIn(want, names)
        self.assertNotIn("review-file", names)

    def test_pr_gate_rejects_ac_proven_only_in_unit_tests(self) -> None:
        # Real-stack proof is re-checked on the head: without the test play's tests it fails.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        code, out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertNotEqual(code, 0)
        self.assertIn("the test play must prove AC through the real stack", out)

    def test_trace_reads_ci_evidence_for_a_ticket_merged_without_committed_evidence(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0)  # no gate ci yet: nothing proves T-042-02
        self.assertIn("T-042-02: done without passing build evidence", out)
        self.assertEqual(self.p.sdlc("gate", "ci")[0], 0)
        code, out = self.p.sdlc("trace")
        self.assertEqual(code, 0, out)


class Conveyor(Base):
    """build -> test -> review -> publish (a note) -> approval, with approvals outside the tree."""

    def test_records_mode_conveyor(self) -> None:
        p = self.p
        p.write("sdlc.toml", p.read("sdlc.toml").replace('mode = "forge"', 'mode = "git"') + "trust_unsigned = true\n")
        p.commit("lead: notes, trust-based")
        for play, agent in (("build", "fake"), ("test", "fake"), ("review", "fake-reviewer")):
            code, out = p.sdlc("run", play, "T-042-02", "--agent", agent)
            self.assertEqual(code, 0, out)
        self.assertFalse((p.root / "evidence" / "T-042-02.build.json").exists())
        self.assertFalse((p.root / "reviews" / "T-042-02.md").exists())
        self.assertIn("status: ready", p.read("tickets/T-042-02-order-page.md"))  # nothing stored
        self.assertIn("Sdlc-Ticket: T-042-02", git(p.root, "log", "-1", "--format=%B"))
        code, out = p.sdlc("review", "publish", "T-042-02")
        self.assertEqual(code, 0, out)
        code, out, res = self.approval()
        self.assertEqual(code, 0, out)
        self.assertTrue(res["trust_based"])
        self.assertEqual(p.sdlc("gate", "pr", "--base", "main")[0], 0)


class ReviewPlay(Base):
    def test_the_review_record_names_the_head_and_every_ac(self) -> None:
        head = self.build()
        rec = self.p.root / ".sdlc-run" / "review-T-042-02.md"
        rec.parent.mkdir(exist_ok=True)
        code, out = self.p.sdlc("gate", "review", "T-042-02", "--only", "review-file")
        self.assertNotEqual(code, 0)
        rec.write_text(approval.render("T-042-02", "0" * 40, "approve", "review", "reviewer", REVIEW_BODY), encoding="utf-8")
        code, out = self.p.sdlc("gate", "review", "T-042-02", "--only", "review-file")
        self.assertIn("commit must be the reviewed HEAD", out)
        rec.write_text(approval.render("T-042-02", head, "approve", "review", "reviewer", REVIEW_BODY), encoding="utf-8")
        code, out = self.p.sdlc("gate", "review", "T-042-02", "--only", "review-file")
        self.assertEqual(code, 0, out)

    def test_publish_posts_the_record_as_a_pr_comment(self) -> None:
        head = self.build()
        self.forge()
        rec = self.p.root / ".sdlc-run" / "review-T-042-02.md"
        rec.parent.mkdir(exist_ok=True)
        rec.write_text(approval.render("T-042-02", head, "approve", "review", "reviewer", REVIEW_BODY), encoding="utf-8")
        code, out = self.p.sdlc("review", "publish", "T-042-02", "--pr", "7")
        self.assertEqual(code, 0, out)
        path, data = self.fake.posted[0]
        self.assertEqual(path, "/issues/7/comments")
        self.assertEqual(approval.parse(data["body"])["commit"], head)


class Tooling(Base):
    def test_doctor_refuses_an_approval_nobody_can_give(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('reviewers = ["rev"]', "reviewers = []"))
        code, out = self.p.sdlc("doctor")
        self.assertIn("approval.mode = forge with no [approval] reviewers", out)
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + "trust_unsigned = true\n")
        code, out = self.p.sdlc("doctor")
        self.assertNotIn("with no [approval] reviewers", out)
        self.assertIn("approvals are trust-based", out)

    def test_migrate_rewrites_delivery_status_and_files(self) -> None:
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("status: ready", "status: in_review"))
        code, out = self.p.sdlc("migrate", "--areas")
        self.assertEqual(code, 0, out)
        t = self.p.read(rel)
        self.assertIn("status: ready", t)
        self.assertIn("\nareas:", t)
        self.assertNotIn("\nfiles:", t)
        self.assertIn("status: done", self.p.read("tickets/T-042-01-returns-api.md"))  # a frozen fact

    def test_followups_draft_tickets_from_an_approval(self) -> None:
        head = self.build()
        self.forge()
        body = REVIEW_BODY.replace("## Findings\n\nNone.", "## Findings\n\n- `app/pages.py:3` cache labels [follow-up]")
        self.record("rev", head, body=body)
        code, out = self.p.sdlc("followups", "--pr", "7")
        self.assertEqual(code, 0, out)
        self.assertIn("1 follow-up ticket(s) drafted", out)
        t = self.p.read("tickets/T-042-03-follow-up.md")
        self.assertIn("status: draft", t)
        self.assertIn('source_review: "PR #7"', t)

    def test_ci_runs_the_base_kit_and_reads_the_pr_head_as_data(self) -> None:
        from helpers import KIT

        wf = (KIT / "adapters" / "github" / "sdlc-approval.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", wf)  # the base branch's workflow, not the PR's
        self.assertIn("ref: ${{ github.event.pull_request.base.ref || github.event.repository.default_branch }}", wf)
        self.assertIn(".sdlc/bin/sdlc --root ../pr-head approval", wf)
        self.assertIn("--publish-status", wf)
        self.assertIn("statuses: write", wf)
        # The gate lives in its own workflow, so a review event can never skip (= pass) it.
        gate = (KIT / "adapters" / "github" / "sdlc.yml").read_text(encoding="utf-8")
        self.assertNotIn("pull_request_review", gate)
        self.assertNotIn("issue_comment", gate)


if __name__ == "__main__":
    unittest.main()
