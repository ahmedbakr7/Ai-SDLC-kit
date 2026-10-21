"""ADR-0001 step 2: approvals bound to the PR's own diff, evidence in CI, status derived from git.
Each new check has a test that catches the defect it exists for and one showing the reference
passes. The forge is faked: CI never touches the network."""
import json
import shutil
import subprocess
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
        self.assertIn("this PR (lead PR) needs an approval from an independent reviewer; a lead approval", res["summary"])
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.record("lead", head, role="lead", agent="", body="ok", ticket="")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)  # pilot finding 17: the lead's own record is not a review
        self.assertIn("this PR (lead PR) needs an approval from an independent reviewer", res["summary"])
        self.record("rev", head, agent="", body="ok", ticket="")
        self.assertEqual(self.approval()[0], 0)

    def test_prompt_review_pr_assembles_a_lead_pr_review(self) -> None:
        # K6: `sdlc prompt review` needed a ticket, so lead PRs got hand-built reviewer prompts.
        mb = git(self.p.root, "rev-parse", "HEAD").strip()
        git(self.p.root, "checkout", "-q", "-b", "lead/docs")
        self.p.write("docs/runbook.md", "# Runbook\n")
        self.p.write("app/sneaky.py", "X = 1\n")
        fe = "skills/frontend-patterns/SKILL.md"
        self.p.write(fe, self.p.read(fe).replace("# Frontend patterns (locked by ADR-0001)",
                                                 "# Frontend patterns (locked by ADR-0001)\n\nPR-EDITED RULE", 1))
        # The PR widening lead_allowed does not make its own code lead-owned: the base's config decides.
        # Moving paths.skills does not hide the base's conventions either.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            "[approval]", '[scope]\nlead_allowed = ["app/**"]\n\n[paths]\nskills = "moved-skills"\n\n[approval]', 1))
        self.p.commit("lead: runbook")
        self.p.write("app/uncommitted.py", "Y = 2\n")  # not in the reviewed range
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        code, text = self.p.sdlc("prompt", "review", "--pr", "7", "--base", "main", "--stdout")
        self.assertEqual(code, 0, text)
        for want in ("# sdlc play: REVIEW lead PR #7", "## Play skill: review", "## Lead PRs", f"- HEAD: `{head}`",
                     f"- BASE: `{mb}`", f"`git diff {mb} {head}`", "- `app/sneaky.py` **(not lead-owned: needs a ticket)**",
                     "- `docs/runbook.md` **(not lead-owned", "- `sdlc.toml`\n", "## Product conventions on main: frontend-patterns",
                     "# Frontend patterns (locked by ADR-0001)", "## Product conventions on main: backend-patterns",
                     "This PR changes `skills/frontend-patterns/SKILL.md`",
                     "`.sdlc-run/lead-review-7.md`", f"`commit: {head}`", "`ticket:` left empty",
                     "`sdlc gate pr --base main`", "`sdlc review publish --pr 7`"):
            self.assertIn(want, text)
        self.assertNotIn("## Ticket ", text)
        self.assertNotIn("uncommitted.py", text)
        self.assertNotIn("PR-EDITED RULE", text)  # the base's conventions, not the PR's
        self.assertEqual(text.count("This PR changes"), 1)
        self.assertIn("This HEAD must be PR #7's head", text)
        code, out = self.p.sdlc("prompt", "review", "--pr", "7", "--base", "nope", "--stdout")
        self.assertNotEqual(code, 0)
        self.assertIn("review --pr 7: cannot find merge base with 'nope'", out)
        git(self.p.root, "checkout", "-q", "main")
        code, text = self.p.sdlc("prompt", "review", "--pr", "7", "--base", "main", "--stdout")
        self.assertEqual(code, 0, text)
        self.assertIn("open every one)\n\n- (none)", text)
        code, out = self.p.sdlc("prompt", "review", "--pr", "7", "--base", "main")
        self.assertEqual((code, out.strip()), (0, ".sdlc-run/prompts/review-pr-7.md"))
        self.assertIn("# sdlc play: REVIEW lead PR #7", self.p.read(".sdlc-run/prompts/review-pr-7.md"))
        for args, why in ((("review",), "or, for a lead PR, --pr N"), (("review", "T-042-02", "--pr", "7"), "without a ticket id"),
                          (("build", "--pr", "7"), "without a ticket id")):
            with self.subTest(args=args):
                code, out = self.p.sdlc("prompt", *args, "--stdout")
                self.assertNotEqual(code, 0)
                self.assertIn(why, out)

    def test_a_lead_pr_review_record_publishes_and_counts(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "lead/docs")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + "\n# a comment\n")
        self.p.commit("lead: comment")
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.forge()
        code, out = self.p.sdlc("review", "publish", "--pr", "7")
        self.assertNotEqual(code, 0)
        self.assertIn("no review record at .sdlc-run/lead-review-7.md", out)
        self.p.write(".sdlc-run/lead-review-7.md", approval.render("T-042-02", head, "approve", "review", "reviewer", "ok"))
        code, out = self.p.sdlc("review", "publish", "--pr", "7")
        self.assertNotEqual(code, 0)
        self.assertIn("is not an approval record for lead PR #7", out)
        text = approval.render("", head, "approve", "review", "reviewer", "ok")
        self.p.write(".sdlc-run/lead-review-7.md", text)
        code, out = self.p.sdlc("review", "publish")
        self.assertNotEqual(code, 0)
        self.assertIn("pass a ticket id, or --pr N", out)
        code, out = self.p.sdlc("review", "publish", "--pr", "7")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fake.posted, [("/issues/7/comments", {"body": text})])
        self.fake.comments.append({"user": {"login": "rev"}, "author_association": "COLLABORATOR",
                                   "created_at": "2026-10-04T10:00:00Z", "body": text})
        self.record("lead", head, role="lead", agent="", body="ok", ticket="")
        code, out, _ = self.approval()
        self.assertEqual(code, 0, out)

    def test_the_review_of_a_lead_pr_comes_from_another_identity(self) -> None:
        # The lead is also a listed reviewer: one identity still cannot be both records.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('reviewers = ["rev"]', 'reviewers = ["rev", "lead"]'))
        self.p.commit("lead: the lead reviews too")
        git(self.p.root, "checkout", "-q", "-b", "lead/tickets")
        self.p.write("docs/plan.md", "a lead artifact\n")
        self.p.commit("plan")
        self.forge(author="ahmed")
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.record("lead", head, role="lead", agent="", body="ok", ticket="")
        self.record("lead", head, role="review", agent="", body="ok", ticket="")
        code, _, res = self.approval()
        self.assertNotEqual(code, 0, res)
        self.assertIn("the review and the lead approval from different identities", res["summary"])
        self.record("rev", head, agent="", body="ok", ticket="")
        self.assertEqual(self.approval()[0], 0, self.approval()[2])

    def test_code_without_a_ticket_needs_the_lead(self) -> None:
        # A forgotten Sdlc-Ticket trailer must not turn a code change into an unapproved lead PR.
        git(self.p.root, "checkout", "-q", "-b", "hotfix")
        self.p.write("app/returns.py", self.p.read("app/returns.py") + "\n# hotfix\n")
        self.p.commit("hotfix without a ticket")
        self.forge()
        code, _, res = self.approval()
        self.assertNotEqual(code, 0)
        self.assertIn("a lead approval (for a PR without a ticket (1 file(s)))", res["summary"])
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.record("lead", head, role="lead", agent="", body="ok", ticket="")
        self.assertNotEqual(self.approval()[0], 0)
        self.record("rev", head, agent="", body="ok", ticket="")
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
        import os
        from unittest import mock

        self.record("rev", self.head)
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/product"}):
            code, out = self.p.sdlc("approval", "--pr", "7")  # no --base: an issue_comment event has none
        self.assertEqual(code, 0, out)

    def test_a_pr_cannot_point_the_token_at_its_own_api(self) -> None:
        # The PR's own sdlc.toml is untrusted: no client carrying the token may be built from it,
        # including the one that looks up the base branch when a comment event names none.
        git(self.p.root, "update-ref", "refs/remotes/origin/main", "main")
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'repo = "owner/product"', 'repo = "owner/product"\napi = "https://attacker.invalid"'))
        self.p.commit("try to redirect the token")
        self.record("rev", git(self.p.root, "rev-parse", "HEAD").strip())
        import os
        from unittest import mock

        seen = []
        approval.forge_client = lambda cfg: seen.append(self._client(cfg).api) or self.fake
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/product"}):
            self.p.sdlc("approval", "--pr", "7", "--publish-status")
        self.assertTrue(seen)
        self.assertNotIn("https://attacker.invalid", seen)

    def test_the_base_lookup_uses_only_the_runner_environment(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": "https://ghe.example/api/v3"}):
            c = self._client(None)
        self.assertEqual((c.repo, c.api), ("o/r", "https://ghe.example/api/v3"))

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
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "in_progress")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("next")
        self.assertNotIn("T-042-02", out)

    def test_a_local_base_behind_the_remote_still_sees_merged_tickets(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        merged = git(self.p.root, "rev-parse", "HEAD").strip()
        git(self.p.root, "update-ref", "refs/remotes/origin/main", merged)
        git(self.p.root, "reset", "-q", "--hard", "HEAD^")  # local main lags origin/main
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")

    def test_a_commit_with_several_play_trailers_counts_for_each(self) -> None:
        from sdlc import config, gate

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        git(self.p.root, "add", "-A")
        git(self.p.root, "commit", "-q", "-m", "both", "-m", "Sdlc-Play: test\nSdlc-Play: build")
        sha = git(self.p.root, "rev-parse", "HEAD").strip()
        self.assertEqual(gate._play_commit(config.load(self.p.root), "main", ("build",)), sha)

    def test_one_play_trailer_with_a_comma_is_one_value(self) -> None:
        from sdlc import config, gate

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        git(self.p.root, "add", "-A")
        git(self.p.root, "commit", "-q", "-m", "not a build", "-m", "Sdlc-Play: other, build")
        self.assertIsNone(gate._play_commit(config.load(self.p.root), "main", ("build",)))

    def test_an_unmerged_branch_makes_a_ready_ticket_in_progress(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "in_progress")
        code, out = self.p.sdlc("next")
        self.assertEqual(code, 3, out)                          # nothing else is ready
        self.assertNotIn("T-042-02", out)
        code, out = self.p.sdlc("status")
        self.assertEqual(code, 0, out)
        self.assertIn("T-042-02\tin_progress\ton build/T-042-02\t", out)
        self.assertIn("1 done, 1 in_progress", out)
        row = json.loads(self.p.sdlc("status", "T-042-02", "--json")[1])
        self.assertEqual((row["status"], row["stored"], row["branches"]), ("in_progress", "ready", ["build/T-042-02"]))

    def test_a_fetched_branch_counts_and_a_deleted_one_frees_the_ticket(self) -> None:
        sha = self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "branch", "-q", "-D", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "ready")
        self.assertEqual(self.p.sdlc("next")[1].strip(), "T-042-02")
        git(self.p.root, "update-ref", "refs/remotes/origin/build/T-042-02", sha)
        self.assertIn("T-042-02\tin_progress\ton origin/build/T-042-02\t", self.p.sdlc("status")[1])
        self.assertNotIn("T-042-02", self.p.sdlc("next")[1])

    def test_the_branch_scan_works_on_git_that_takes_one_no_merged(self) -> None:
        from unittest import mock

        from sdlc import config
        from sdlc.artifacts import Repo

        sha = self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "update-ref", "refs/remotes/origin/main", "main")  # two bases, as after a fetch
        real = gitutil.git

        def old_git(root, *args, check=True):  # git < 2.29 refuses a second --no-merged
            if sum(a.startswith("--no-merged") for a in args) > 1:
                if check:
                    raise gitutil.GitError("only one --no-merged allowed")
                return ""
            return real(root, *args, check=check)

        with mock.patch.object(gitutil, "git", old_git):
            self.assertEqual(Repo(config.load(self.p.root)).in_flight(), {"T-042-02": ["build/T-042-02"]})
        git(self.p.root, "update-ref", "refs/remotes/origin/main", sha)  # merged into one base only
        self.assertEqual(Repo(config.load(self.p.root)).in_flight(), {})

    def test_a_failed_branch_scan_raises_instead_of_freeing_every_ticket(self) -> None:
        from unittest import mock

        from sdlc import config
        from sdlc.artifacts import Repo

        self.build()
        real = gitutil.git

        def broken(root, *args, check=True):
            if args[:1] == ("for-each-ref",):
                if check:
                    raise gitutil.GitError("for-each-ref failed")
                return ""
            return real(root, *args, check=check)

        with mock.patch.object(gitutil, "git", broken), self.assertRaises(gitutil.GitError):
            Repo(config.load(self.p.root)).in_flight()

    def test_a_branch_does_not_move_a_lead_decision(self) -> None:
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("status: ready", "status: blocked\nblocked_by: waiting on legal"))
        self.p.commit("lead: block T-042-02")
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "blocked")
        self.assertIn("T-042-02\tblocked\tblocked: waiting on legal\t", self.p.sdlc("status")[1])

    def test_the_runner_will_not_build_a_ticket_another_branch_is_building(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "someone-else")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "T-042-02: started elsewhere")
        git(self.p.root, "checkout", "-q", "main")
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02 is in progress on someone-else", out)
        git(self.p.root, "branch", "-q", "-m", "someone-else", "build/T-042-02")  # its own branch resumes
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("would checkout build/T-042-02", out)

    def test_the_runner_resumes_its_own_fetched_branch(self) -> None:
        # ADR-0003: the runner exempts <branch> and origin/<branch>, nothing else.
        sha = self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "branch", "-q", "-D", "build/T-042-02")
        run = lambda: self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        git(self.p.root, "update-ref", "refs/remotes/origin/build/T-042-02", sha)
        code, out = run()
        self.assertEqual(code, 0, out)                          # the ticket's own branch, fetched
        git(self.p.root, "update-ref", "-d", "refs/remotes/origin/build/T-042-02")
        git(self.p.root, "update-ref", "refs/remotes/origin/x/build/T-042-02", sha)  # another remote branch
        code, out = run()
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02 is in progress on origin/x/build/T-042-02", out)
        git(self.p.root, "update-ref", "-d", "refs/remotes/origin/x/build/T-042-02")
        git(self.p.root, "branch", "-q", "someone/build/T-042-02", sha)  # a local branch, not a remote's
        code, out = run()
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02 is in progress on someone/build/T-042-02", out)

    def test_a_real_build_resumes_the_fetched_branch_with_its_commits(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        sha = commit(self.p, "T-042-02: started on another machine")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "branch", "-q", "-D", "build/T-042-02")
        git(self.p.root, "update-ref", "refs/remotes/origin/build/T-042-02", sha)
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.p.root, "branch", "--show-current").strip(), "build/T-042-02")
        # The fetched commit is under the new work, not dropped for a fresh branch off main.
        git(self.p.root, "merge-base", "--is-ancestor", sha, "HEAD")  # raises if it is not

    def test_the_runner_refuses_a_build_it_cannot_check_for_other_branches(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "work")
        git(self.p.root, "branch", "-q", "-D", "main")              # no base, local or fetched
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertNotEqual(code, 0, out)
        self.assertIn("vcs.base 'main' is neither a local branch nor on origin", out)

    def test_an_unknown_dependency_is_not_done(self) -> None:
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("depends_on:\n", "depends_on:\n  - T-042-99\n", 1))
        self.p.commit("lead: a dependency that does not exist")
        self.assertIn("T-042-02\tready\twaiting on T-042-99\t", self.p.sdlc("status")[1])
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertNotEqual(code, 0, out)
        self.assertIn("pending: T-042-99", out)

    def test_delivery_statuses_are_not_stored(self) -> None:
        code, out = self.p.sdlc("status", "T-042-02", "in_progress", "--as", "build")
        self.assertNotEqual(code, 0)
        self.assertIn("in_progress is derived, not stored", out)
        self.assertIn("unmerged branch", out)                   # ADR-0003, not open PRs
        code, out = self.p.sdlc("status", "T-042-02", "in_review", "--as", "build")
        self.assertNotEqual(code, 0)
        self.assertIn("in_review is not stored, and records mode does not derive it", out)
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("status: ready", "status: in_progress"))
        code, out = self.p.sdlc("lint")
        self.assertIn("status in_progress is derived, not stored", out)
        self.p.write(rel, self.p.read(rel).replace("status: in_progress", "status: in_review"))
        code, out = self.p.sdlc("lint")
        self.assertIn("status in_review is not stored (ADR-0003: under review reads in_progress)", out)

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

    def test_ci_re_proves_a_merged_ticket_whose_stored_status_is_not_done(self) -> None:
        # Its file still says ready; the merged trailer makes it done, so CI owes its real-stack proof.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02: done, but no passing integration/e2e test carries its tag", out)

    def lead_sets(self, old: str, new: str, ticket: str = "tickets/T-042-02-order-page.md") -> None:
        """A lead decision on main: edit the ticket's front matter there."""
        git(self.p.root, "checkout", "-q", "main")
        self.p.write(ticket, self.p.read(ticket).replace(old, new, 1))
        self.p.commit("lead: edit T-042-02")

    def merge_build_only(self) -> None:
        """T-042-02 merged with its AC proven by unit tests only."""
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")

    def test_pr_gate_takes_unit_proof_for_a_refactor_ticket(self) -> None:
        # Hangout pilot (T-001-68): ADR-0004 makes the refactor build's full suite the proof and
        # refuses the test play, so gate pr must not ask for a real-stack tag the lane cannot get.
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        self.p.sdlc("gate", "pr", "--base", "main", "--only", "unit,ac-coverage")
        ev = json.loads(self.p.read(".sdlc-run/T-042-02.pr.json"))
        self.assertEqual(ev["lane"], "refactor")
        c = {x["name"]: x for x in ev["checks"]}["ac-coverage"]
        self.assertEqual(c["status"], "pass", c)

    def test_a_refactor_ticket_the_diff_raises_owes_real_stack_proof(self) -> None:
        # The exemption follows the lane the gate resolved: raised out of refactor, the ticket
        # has a test play again, and that play owes the real-stack tag.
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[lanes]\nstrict_paths = ["app/pages.py"]\n')
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        code, out = self.p.sdlc("gate", "pr", "--base", "main", "--only", "unit,ac-coverage")
        ev = json.loads(self.p.read(".sdlc-run/T-042-02.pr.json"))
        self.assertEqual(ev["lane"], "strict")
        self.assertIn("the test play must prove AC through the real stack", out)

    def test_ci_takes_unit_proof_for_a_merged_refactor_ticket(self) -> None:
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        self.merge_build_only()
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertEqual(code, 0, out)

    def test_a_refactor_ticket_still_needs_a_passing_tagged_test(self) -> None:
        # Only the real-stack requirement goes: AC with no passing tagged test still fail.
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        self.merge_build_only()
        test = self.p.root / "app" / "test_pages.py"
        test.write_text(test.read_text(encoding="utf-8").replace("T-042-02/AC-", "T-042-02-AC-"), encoding="utf-8")
        self.p.commit("main: T-042-02's tests lose their tags")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("AC without a passing test", out)

    def test_a_branch_cannot_declare_a_lane_to_drop_a_shipped_tickets_proof(self) -> None:
        self.merge_build_only()
        git(self.p.root, "checkout", "-q", "-b", "lead/relabel")
        rel = "tickets/T-042-02-order-page.md"
        self.p.write(rel, self.p.read(rel).replace("risk: low\n", "risk: low\nlane: refactor\n", 1))
        self.p.commit("relabel T-042-02 as a refactor")
        code, out = self.p.sdlc("gate", "ci", "--base", "main", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02: done, but no passing integration/e2e test carries its tag", out)

    def test_ci_owes_no_real_stack_proof_for_a_ticket_without_ac(self) -> None:
        # Hangout pilot (T-001-69): a mechanical ticket with acceptance_criteria: [] has no tag to
        # carry, so CI must not call it unproven after it merges.
        rel = "tickets/T-042-02-order-page.md"
        text = self.p.read(rel)
        start = text.index("acceptance_criteria:\n")
        end = text.index("source_intent:")
        self.lead_sets(text[start:end], "acceptance_criteria: []\n")
        self.merge_build_only()
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertEqual(code, 0, out)
        self.assertNotIn("T-042-02: done, but", out)

    def raised_refactor(self) -> None:
        """T-042-02 declared refactor on main; its build touches a strict path, so it ships strict."""
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + '\n[lanes]\nstrict_paths = ["app/pages.py"]\n')
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        commit(self.p, "build and test")

    def pr_checks(self) -> dict:
        self.p.sdlc("gate", "pr", "--base", "main")
        return {x["name"]: x for x in json.loads(self.p.read(".sdlc-run/T-042-02.pr.json"))["checks"]}

    def test_a_pr_that_raises_a_refactor_ticket_must_record_its_lane(self) -> None:
        # Issue #51: once merged, CI sees only the declared lane, so the PR records the real one.
        self.raised_refactor()
        c = self.pr_checks()["lane-record"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("declares lane refactor but ships as strict", c["summary"])
        self.assertIn("--lane strict --allow-empty", c["details"][0])
        code, out = self.p.sdlc("commit", "T-042-02", "--agent", "builder", "--play", "build", "--lane", "bogus",
                                "--allow-empty", "-m", "lane")
        self.assertNotEqual(code, 0, out)
        self.assertIn("--lane must be one of", out)
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "not a lane",
            "-m", "Sdlc-Ticket: T-042-02\nSdlc-Lane: bogus")             # an unknown lane records nothing
        self.assertIn("lane-record", self.pr_checks())
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "other ticket",
            "-m", "Sdlc-Ticket: T-042-99\nSdlc-Lane: strict")             # another ticket's record
        self.assertIn("lane-record", self.pr_checks())
        code, out = self.p.sdlc("commit", "T-042-02", "--agent", "builder", "--play", "build", "--lane", "strict",
                                "--allow-empty", "-m", "lane T-042-02: strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("lane-record", self.pr_checks())

    def test_a_pr_that_keeps_its_declared_lane_records_nothing(self) -> None:
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        self.assertNotIn("lane-record", self.pr_checks())

    def test_ci_keeps_asking_a_raised_ticket_for_real_stack_proof(self) -> None:
        # Merged with only unit proof but a recorded strict lane: the exemption no longer applies.
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        commit(self.p, "build only")
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "lane", "-m",
            "Sdlc-Agent: builder\nSdlc-Play: build\nSdlc-Ticket: T-042-02\nSdlc-Lane: strict")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        code, out = self.p.sdlc("gate", "ci", "--only", "unit,integration,ac-coverage")
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02: done, but no passing integration/e2e test carries its tag", out)

    def test_the_runner_records_the_lane_a_build_raised(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('mode = "forge"', 'mode = "git"')
                     + 'trust_unsigned = true\n\n[lanes]\nstrict_paths = ["app/pages.py"]\n')
        self.lead_sets("risk: low\n", "risk: low\nlane: refactor\n")
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake")
        self.assertIn("recorded lane strict for T-042-02 (declared refactor)", out)
        self.assertIn("Sdlc-Lane: strict", git(self.p.root, "log", "--format=%B", "main..HEAD"))

    def make_shallow(self, at: str = "main") -> None:
        """What Playwright's captureGitInfo leaves: a shallow boundary at the PR base, every
        commit still present."""
        sha = git(self.p.root, "rev-parse", at).strip()
        (self.p.root / ".git" / "shallow").write_text(sha + "\n", encoding="utf-8")

    def test_a_shallow_repository_fails_gate_pr_before_it_reads_trailers(self) -> None:
        # Hangout pilot: past the boundary, merge-base..HEAD leaked every ticket merged since
        # the branch's fork point, and gate pr reported "this branch moves 31 tickets".
        self.build()
        self.make_shallow()
        code, out = self.p.sdlc("gate", "pr", "--base", "main")
        self.assertNotEqual(code, 0)
        self.assertIn("gate pr: the repository is shallow (.git/shallow)", out)
        self.assertNotIn("this branch moves", out)

    def test_a_shallow_repository_fails_trace(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("gate", "ci")[0], 0)
        self.assertEqual(self.p.sdlc("trace")[0], 0)
        self.make_shallow("HEAD")  # T-042-02's trailer is past the boundary: it would read ready
        code, out = self.p.sdlc("trace")
        self.assertNotEqual(code, 0)
        self.assertIn("ERROR the repository is shallow (.git/shallow)", out)

    def test_gate_fails_when_a_check_makes_the_repository_shallow(self) -> None:
        # The history check runs after the others: a tool run by a check may cut history mid-run.
        main = git(self.p.root, "rev-parse", "main").strip()
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace(
            'unit = "python tools/junit.py --start app --out {junit}"',
            f'unit = "python -c \\"open(\'.git/shallow\', \'w\').write(\'{main}\\\\n\')\\" '
            '&& python tools/junit.py --start app --out {junit}"', 1))
        self.p.commit("lead: a unit command that cuts history, as a test tool might")
        code, out = self.p.sdlc("gate", "ci")
        self.assertTrue((self.p.root / ".git" / "shallow").is_file())
        self.assertNotEqual(code, 0, out)
        ev = json.loads(self.p.read(".sdlc-run/ci.json"))
        c = {x["name"]: x for x in ev["checks"]}["history"]
        self.assertEqual(c["status"], "fail")
        self.assertIn("is shallow", c["summary"])

    def test_a_full_repository_adds_no_history_check(self) -> None:
        self.assertEqual(self.p.sdlc("gate", "ci")[0], 0)
        ev = json.loads(self.p.read(".sdlc-run/ci.json"))
        self.assertNotIn("history", [x["name"] for x in ev["checks"]])

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

    def test_the_review_prompt_names_one_commit_for_the_record(self) -> None:
        # Pilot finding 4: the prompt said both "Set `commit: <proven>`" and "the HEAD you
        # reviewed". The record must name HEAD, which review-file checks.
        proven = self.build()
        run = self.p.root / ".sdlc-run"
        run.mkdir(exist_ok=True)
        (run / "T-042-02.build.json").write_text(json.dumps({"result": "pass", "commit": proven, "dirty": False,
                                                              "checks": [], "ac": {}}), encoding="utf-8")
        self.p.write("app/pages.py", self.p.read("app/pages.py") + "\n")
        commit(self.p, "T-042-02: tidy")
        code, out = self.p.sdlc("prompt", "review", "T-042-02")
        self.assertEqual(code, 0, out)
        text = self.p.read(".sdlc-run/prompts/review-T-042-02.md")
        self.assertNotIn(f"Set `commit: {proven}`", text)
        self.assertIn(f"The latest local evidence is for `{proven}`. The record's `commit:` is the HEAD you reviewed",
                      text)

    def test_a_gate_on_a_dirty_tree_says_it_proves_no_commit(self) -> None:
        # Pilot finding 3: gating before committing recorded the commit below the changes as proven.
        self.build()
        out = self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")[1]
        self.assertIn("gate build T-042-02", out)
        self.assertNotIn("proves no commit", out)
        self.p.write("app/pages.py", self.p.read("app/pages.py") + "\n")
        out = self.p.sdlc("gate", "build", "T-042-02", "--only", "scope")[1]
        self.assertIn("note: the tree has uncommitted changes, so this run proves no commit", out)

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
        self.assertIn(".sdlc/bin/sdlc --root ../pr-head approval", wf)
        self.assertIn("--publish-status", wf)
        # The base is resolved from the event or the GitHub API, never from the PR's sdlc.toml.
        self.assertIn('--base "origin/$BASE"', wf)
        self.assertNotIn("${BASE:+", wf)
        # Git over HTTPS rejects a bearer token; it takes basic auth with x-access-token.
        self.assertNotIn("bearer", wf)
        self.assertIn("x-access-token:%s", wf)
        # Reviews never run the privileged job: pull_request_review runs the PR's copy of a
        # workflow, and on a fork its token cannot write a status. An unprivileged relay records
        # the PR number; the judge runs on workflow_run, always from the default branch.
        on = wf.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]
        self.assertNotIn("pull_request_review", on)
        self.assertIn("  workflow_run:\n    workflows: [sdlc-approval-review]\n    types: [completed]\n", on)
        self.assertIn("*[!0-9]*", wf)  # the relayed PR number is data: digits only
        # The PR and its base are known before the checkout, so the kit (and the config it
        # judges by) come from the PR's own base branch, even when that is not the default.
        self.assertLess(wf.index("- name: Which PR and base"), wf.index("uses: actions/checkout@v4"))
        self.assertIn("ref: ${{ needs.which.outputs.base }}", wf)
        # One judge per PR at a time, newest last: an older run cannot post after a newer one.
        self.assertIn("    concurrency:\n      group: sdlc-approval-${{ needs.which.outputs.pr }}\n"
                      "      cancel-in-progress: false\n", wf)
        relay = (KIT / "adapters" / "github" / "sdlc-approval-review.yml").read_text(encoding="utf-8")
        self.assertIn("\nname: sdlc-approval-review\n", relay)
        self.assertIn("\npermissions: {}\n", relay)
        self.assertIn("  pull_request_review:\n    types: [submitted, edited, dismissed]\n", relay)
        self.assertIn("types: [opened, synchronize, reopened, edited]", wf)  # retargeting re-judges
        self.assertIn("statuses: write", wf)
        # The gate lives in its own workflow, so a review event can never skip (= pass) it.
        gate = (KIT / "adapters" / "github" / "sdlc.yml").read_text(encoding="utf-8")
        self.assertNotIn("pull_request_review", gate)
        self.assertNotIn("issue_comment", gate)


class HardenedPreset(Base):
    """ADR-0002 step 4c: under `[gate] preset = "hardened"` a mechanical PR needs a human
    reviewer; a bot's approval alone, enough by default, does not count."""

    def mechanical_pr(self) -> str:
        from test_lanes import MECH, MECH_TICKET, rename

        git(self.p.root, "checkout", "-q", "-b", "build/T-042-03")
        self.p.write(MECH, MECH_TICKET)
        rename(self.p)
        return commit(self.p, "T-042-03 rename", ticket="T-042-03")

    def test_a_bot_alone_passes_a_mechanical_pr_by_default(self) -> None:
        head = self.mechanical_pr()
        self.forge()
        self.record("bot", head, role="bot", ticket="T-042-03")
        code, out, res = self.approval()
        self.assertEqual(code, 0, (out, res))
        self.assertIn("(mechanical) approved", res["summary"])

    def test_hardened_needs_a_human_reviewer(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace("[approval]", '[gate]\npreset = "hardened"\n\n[approval]', 1))
        self.p.commit("lead: hardened")
        head = self.mechanical_pr()
        self.forge()
        self.record("bot", head, role="bot", ticket="T-042-03")
        code, out, res = self.approval()
        self.assertNotEqual(code, 0, (out, res))
        self.assertIn("(mechanical) needs an approval from an independent reviewer", res["summary"])
        self.record("rev", head, ticket="T-042-03")
        self.assertEqual(self.approval()[0], 0)



class PilotGaps(Base):
    """Hangout pilot, kit v1.5.0: what let a ticket through unnoticed."""

    def unnamed_build(self) -> str:
        # The build commit names its ticket but no agent, like Hangout #73's a11821e.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        git(self.p.root, "add", "-A")
        git(self.p.root, "commit", "-q", "-m", "T-042-02: order page returns section", "-m", "Sdlc-Ticket: T-042-02")
        return git(self.p.root, "rev-parse", "HEAD").strip()

    def test_a_commit_without_an_agent_trailer_leaves_independence_unchecked(self) -> None:
        # Nothing named the builder, so the builder's own record looked independent.
        head = self.unnamed_build()
        self.forge()
        self.record("rev", head, agent="builder")
        code, out, res = self.approval()
        self.assertNotEqual(code, 0, (out, res))
        self.assertIn(f"needs Sdlc-Agent trailers on 1 commit(s) ({head[:7]}) to check reviewer independence",
                      res["summary"])

    def test_every_commit_naming_its_agent_lets_the_independent_review_count(self) -> None:
        head = self.build()
        self.forge()
        self.record("rev", head)
        code, out, res = self.approval()
        self.assertEqual(code, 0, (out, res))

    def test_sdlc_commit_names_the_agent_so_its_review_is_checked(self) -> None:
        # The IDE path: an agent commits with `sdlc commit`, and the builder's own record fails.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        git(self.p.root, "add", "-A")
        code, out = self.p.sdlc("commit", "T-042-02", "-m", "T-042-02: order page", "--agent", "builder",
                                "--play", "build")
        self.assertEqual(code, 0, out)
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.assertIn("Sdlc-Agent: builder\nSdlc-Play: build\nSdlc-Ticket: T-042-02", git(self.p.root, "log", "-1", "--format=%B"))
        self.forge()
        self.record("rev", head, agent="builder")
        self.assertNotEqual(self.approval()[0], 0)
        self.record("rev", head, at="2026-10-04T11:00:00Z")
        self.assertEqual(self.approval()[0], 0)
        self.assertNotEqual(self.p.sdlc("commit", "T-042-02", "-m", "no agent")[0], 0)

    def test_sdlc_commit_keeps_the_trailers_the_message_already_has(self) -> None:
        # Pilot finding 2: the kit's trailers went into a paragraph of their own, so git no
        # longer read the message's Co-Authored-By as a trailer.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        git(self.p.root, "add", "-A")
        code, out = self.p.sdlc("commit", "T-042-02", "-m", "T-042-02: order page\n\nCo-Authored-By: Pair <pair@example.com>",
                                "--agent", "builder", "--play", "build")
        self.assertEqual(code, 0, out)
        trailers = git(self.p.root, "log", "-1", "--format=%(trailers:only,unfold)")
        self.assertEqual(trailers.split("\n")[:4], ["Co-Authored-By: Pair <pair@example.com>", "Sdlc-Agent: builder",
                                                     "Sdlc-Play: build", "Sdlc-Ticket: T-042-02"])

    def test_an_extra_agent_trailer_does_not_hide_the_builder(self) -> None:
        # The builder's message also names `Sdlc-Agent: other`. Read joined, the two were one
        # agent "other,builder", and the builder's own record looked independent.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        git(self.p.root, "add", "-A")
        code, out = self.p.sdlc("commit", "T-042-02", "-m", "T-042-02: order page\n\nSdlc-Agent: other",
                                "--agent", "builder", "--play", "build")
        self.assertEqual(code, 0, out)
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.forge()
        self.record("rev", head, agent="builder")
        code, out, res = self.approval()
        self.assertNotEqual(code, 0, (out, res))
        self.assertIn("builder", out)
        self.record("rev", head, at="2026-10-04T11:00:00Z")
        self.assertEqual(self.approval()[0], 0)

    def test_a_separator_inside_an_agent_name_does_not_hide_the_builder(self) -> None:
        # `Sdlc-Agent: other|review` once split the record at its pipe, moving `builder` into
        # the plays field.
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        copy_solution(self.p, "build-T-042-02")
        copy_solution(self.p, "test-T-042-02")
        git(self.p.root, "add", "-A")
        code, out = self.p.sdlc("commit", "T-042-02", "-m", "T-042-02: order page\n\nSdlc-Agent: other|review",
                                "--agent", "builder", "--play", "build")
        self.assertEqual(code, 0, out)
        head = git(self.p.root, "rev-parse", "HEAD").strip()
        self.forge()
        self.record("rev", head, agent="builder")
        code, out, res = self.approval()
        self.assertNotEqual(code, 0, (out, res))
        self.record("rev", head, at="2026-10-04T11:00:00Z")
        self.assertEqual(self.approval()[0], 0)

    def squash_merge(self) -> None:
        # What a forge's squash merge writes: every commit message folded into one body, the
        # trailers no longer in the last paragraph.
        self.build()
        msg = git(self.p.root, "log", "-1", "--format=%B").strip()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--squash", "build/T-042-02")
        git(self.p.root, "commit", "-q", "-m", "T-042-02: order page returns section (#7)",
            "-m", "* " + msg, "-m", "---------", "-m", "Co-authored-by: someone <someone@example.com>")

    def test_a_squash_merged_ticket_fails_gate_ci_until_it_is_reverted_and_merged(self) -> None:
        self.squash_merge()
        # What the trailers say: not delivered, and its branch is still unmerged.
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "in_progress")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("1 merged commit(s) name Sdlc-Ticket outside their trailers", out)
        self.assertIn("names T-042-02 in its body, not as a trailer", out)
        git(self.p.root, "revert", "--no-edit", "HEAD")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)
        self.assertNotIn("trailers", out)

    def test_merging_the_original_commits_after_a_squash_clears_it_without_a_revert(self) -> None:
        # Hangout T-001-33: the squash pruned the baseline, so a revert would regrow it. Merging
        # the PR's own commits delivers the ticket as a trailer, and the squash is then harmless.
        self.squash_merge()
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)
        self.assertNotIn("outside their trailers", out)

    def test_a_squash_of_two_tickets_still_fails_for_the_one_not_delivered(self) -> None:
        # CodeRabbit on kit #28: delivering one buried ticket must not clear the squash's other.
        self.build()
        msg = git(self.p.root, "log", "-1", "--format=%B").strip()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--squash", "build/T-042-02")
        git(self.p.root, "commit", "-q", "-m", "two tickets in one squash (#8)", "-m", "* " + msg,
            "-m", "* other work\n\nSdlc-Ticket: T-042-09", "-m", "---------",
            "-m", "Co-authored-by: someone <someone@example.com>")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("names T-042-09 in its body, not as a trailer", out)
        self.assertNotIn("names T-042-02", out)

    def test_a_revert_message_without_the_reverse_change_does_not_exempt_the_squash(self) -> None:
        self.squash_merge()
        squash = git(self.p.root, "rev-parse", "HEAD").strip()
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "Revert", "-m", f"This reverts commit {squash}.")
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("names T-042-02 in its body, not as a trailer", out)

    def test_reverting_the_revert_brings_the_squash_back_into_the_report(self) -> None:
        self.squash_merge()
        git(self.p.root, "revert", "--no-edit", "HEAD")
        self.assertEqual(self.p.sdlc("gate", "ci")[0], 0)
        git(self.p.root, "revert", "--no-edit", "HEAD")  # the squash's change is back
        code, out = self.p.sdlc("gate", "ci")
        self.assertNotEqual(code, 0, out)
        self.assertIn("names T-042-02 in its body, not as a trailer", out)

    def test_a_merge_commit_keeps_the_trailers_and_gate_ci_has_nothing_to_report(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "merge", "-q", "--no-ff", "--no-edit", "build/T-042-02")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "done")
        code, out = self.p.sdlc("gate", "ci")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Sdlc-Ticket outside", out)


class Claims(Base):
    """ADR-0005: vcs.claim = "push" claims a ticket on origin before the agent runs; claim_days
    frees a branch nobody commits to; --prs shows open PRs. The agent here leaves the branch at
    once, so the run stops before the gate: the claim is what is under test."""
    extra = '\n[vcs]\nclaim = "push"\n\n[agents.leaver]\ncommand = "git checkout -q main"\n'

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.p.root.parent / "origin.git"
        git(self.p.root.parent, "clone", "-q", "--bare", str(self.p.root), str(self.origin))
        git(self.p.root, "remote", "add", "origin", str(self.origin))
        git(self.p.root, "fetch", "-q", "origin")
        self.other = self.p.root.parent / "other"
        git(self.p.root.parent, "clone", "-q", str(self.origin), str(self.other))
        git(self.other, "config", "user.email", "other@example.com")
        git(self.other, "config", "user.name", "other machine")

    def run_build(self, root, *extra: str) -> tuple[int, str]:
        import contextlib
        import io

        from sdlc import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(["--root", str(root), "run", "build", "T-042-02", "--agent", "leaver", *extra])
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if not isinstance(e.code, int) and e.code:
                    print(e.code)
        return code, out.getvalue()

    def remote_tip(self) -> str:
        return git(self.origin, "log", "-1", "--format=%s%n%B", "refs/heads/build/T-042-02")

    def test_a_build_pushes_its_claim_before_the_agent_runs(self) -> None:
        code, out = self.run_build(self.p.root)
        self.assertIn("claimed T-042-02: pushed build/T-042-02 to origin", out)
        self.assertIn("the agent left build/T-042-02", out)          # the agent ran after the claim
        tip = self.remote_tip()
        self.assertIn("claim T-042-02", tip)
        self.assertIn("Sdlc-Ticket: T-042-02", tip)
        self.assertIn("Sdlc-Agent: leaver", tip)

    def test_another_clone_is_refused_until_it_takes_over(self) -> None:
        self.run_build(self.p.root)
        code, out = self.run_build(self.other)
        self.assertNotEqual(code, 0, out)
        self.assertIn("T-042-02 is claimed by origin/build/T-042-02", out)
        self.assertIn("--take-over", out)
        self.assertEqual(git(self.other, "branch", "--show-current").strip(), "main")
        code, out = self.run_build(self.other, "--take-over")
        self.assertNotIn("refused", out)
        self.assertIn("the agent left build/T-042-02", out)

    def test_git_refuses_the_second_of_two_racing_claims(self) -> None:
        from unittest import mock

        from sdlc import run

        with mock.patch.object(run, "_fetch", lambda root: None):  # the other clone fetched before the claim
            self.run_build(self.p.root)
            code, out = self.run_build(self.other)
        self.assertNotEqual(code, 0, out)
        self.assertIn("refused: could not claim T-042-02 by pushing build/T-042-02", out)
        # The losing run leaves nothing behind: back where it started, no local claim branch.
        self.assertEqual(git(self.other, "branch", "--show-current").strip(), "main")
        self.assertEqual(git(self.other, "branch", "--list", "build/T-042-02").strip(), "")
        self.assertIn("Sdlc-Agent: leaver", self.remote_tip())
        self.assertEqual(git(self.origin, "log", "-1", "--format=%ae", "refs/heads/build/T-042-02").strip(),
                         "kit@example.com")                          # the first claim stands

    def test_a_claim_needs_the_remote(self) -> None:
        git(self.p.root, "remote", "remove", "origin")
        code, out = self.run_build(self.p.root)
        self.assertNotEqual(code, 0, out)
        self.assertIn('vcs.claim = "push" fetches origin before claiming, and the fetch failed', out)
        self.assertEqual(git(self.p.root, "branch", "--list", "build/T-042-02").strip(), "")

    def test_a_resumed_branch_gets_a_fresh_claim_on_top(self) -> None:
        sha = self.build()
        git(self.p.root, "checkout", "-q", "main")
        self.run_build(self.p.root)
        tip = git(self.origin, "rev-parse", "refs/heads/build/T-042-02").strip()
        self.assertNotEqual(tip, sha)
        self.assertEqual(git(self.origin, "rev-parse", f"{tip}^").strip(), sha)
        self.assertIn("claim T-042-02", self.remote_tip())

    def test_two_claims_from_one_identity_on_one_tick_differ(self) -> None:
        self.run_build(self.p.root)
        first = git(self.origin, "log", "-1", "--format=%(trailers:key=Sdlc-Claim,valueonly)",
                    "refs/heads/build/T-042-02").strip()
        self.assertRegex(first, r"^[0-9a-f-]{36}$")

    def expired_origin_branch(self) -> None:
        """origin/build/T-042-02 names the ticket, last commit long ago; claims expire after 3 days."""
        from helpers import git_env
        import subprocess

        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('claim = "push"', 'claim = "push"\nclaim_days = 3'))
        self.p.commit("lead: claims expire")
        git(self.p.root, "push", "-q", "origin", "main")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        old = "2026-01-01T00:00:00Z"
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "stalled", "-m", "Sdlc-Ticket: T-042-02"],
                       cwd=self.p.root, check=True, env=git_env(GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old))
        git(self.p.root, "push", "-q", "origin", "build/T-042-02")
        git(self.p.root, "checkout", "-q", "main")
        git(self.p.root, "branch", "-q", "-D", "build/T-042-02")
        git(self.other, "pull", "-q", "origin", "main")

    def test_an_expired_claim_is_taken_by_one_run_only(self) -> None:
        # Review of #52: an expired branch already names the ticket; pushed unchanged, every run
        # "claimed" it at once and the claim stayed expired.
        from unittest import mock

        from sdlc import run

        self.expired_origin_branch()
        git(self.other, "fetch", "-q", "origin")
        code, out = self.run_build(self.p.root)                     # no --take-over: the claim expired
        self.assertIn("claimed T-042-02", out)
        with mock.patch.object(run, "_fetch", lambda root: None):   # fetched before that claim
            code, out = self.run_build(self.other)
        self.assertNotEqual(code, 0, out)
        self.assertIn("refused: could not claim T-042-02", out)
        code, out = self.run_build(self.other)                      # after a fetch: a live claim
        self.assertIn("T-042-02 is claimed by origin/build/T-042-02", out)

    def test_two_take_overs_cannot_both_win(self) -> None:
        from unittest import mock

        from sdlc import run

        self.run_build(self.p.root)
        third = self.p.root.parent / "third"
        git(self.p.root.parent, "clone", "-q", str(self.origin), str(third))
        git(third, "config", "user.email", "third@example.com")
        git(third, "config", "user.name", "third machine")
        git(self.other, "fetch", "-q", "origin")
        code, out = self.run_build(self.other, "--take-over")
        self.assertIn("claimed T-042-02", out)
        with mock.patch.object(run, "_fetch", lambda root: None):   # fetched before the first take-over
            code, out = self.run_build(third, "--take-over")
        self.assertNotEqual(code, 0, out)
        self.assertIn("refused: could not claim T-042-02", out)
        # The displaced holder learns on its next push: it is no longer a fast-forward.
        r = subprocess.run(["git", "push", "-q", "origin", "build/T-042-02"], cwd=self.p.root, capture_output=True)
        self.assertNotEqual(r.returncode, 0)

    def test_a_refused_push_puts_an_existing_local_branch_back(self) -> None:
        from unittest import mock

        from sdlc import run

        self.run_build(self.other)                                  # the other clone claims first
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02", "main")
        git(self.p.root, "checkout", "-q", "main")
        before = git(self.p.root, "rev-parse", "build/T-042-02").strip()
        with mock.patch.object(run, "_fetch", lambda root: None), \
                mock.patch.object(run, "_claim_problem", lambda *a: None):
            code, out = self.run_build(self.p.root)
        self.assertIn("refused: could not claim T-042-02", out)
        self.assertEqual(git(self.p.root, "rev-parse", "build/T-042-02").strip(), before)
        self.assertEqual(git(self.p.root, "branch", "--show-current").strip(), "main")

    def test_a_failed_claim_commit_leaves_nothing_behind(self) -> None:
        hook = self.p.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        code, out = self.run_build(self.p.root)
        self.assertNotEqual(code, 0, out)
        self.assertIn("refused: could not commit the claim for T-042-02", out)
        self.assertEqual(git(self.p.root, "branch", "--show-current").strip(), "main")
        self.assertEqual(git(self.p.root, "branch", "--list", "build/T-042-02").strip(), "")

    def test_diverged_local_and_remote_branches_are_refused(self) -> None:
        self.run_build(self.other)                                   # the other clone claims first
        git(self.p.root, "fetch", "-q", "origin")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02", "main")
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "mine")
        git(self.p.root, "checkout", "-q", "main")
        code, out = self.run_build(self.p.root)
        self.assertNotEqual(code, 0, out)
        self.assertIn("build/T-042-02 and origin/build/T-042-02 have diverged", out)

    def test_take_over_needs_push_claims(self) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('claim = "push"', 'claim = "local"'))
        self.p.commit("lead: local claims")
        code, out = self.run_build(self.p.root, "--take-over")
        self.assertNotEqual(code, 0, out)
        self.assertIn('--take-over continues another run\'s claim; it needs records mode, build and vcs.claim = "push"', out)

    def test_an_expired_claim_frees_the_ticket(self) -> None:
        from helpers import git_env
        import subprocess

        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('claim = "push"', 'claim = "local"\nclaim_days = 3'))
        self.p.commit("lead: claims expire")
        git(self.p.root, "checkout", "-q", "-b", "someone-else")
        copy_solution(self.p, "build-T-042-02")
        git(self.p.root, "add", "-A")
        old = "2026-01-01T00:00:00Z"
        subprocess.run(["git", "commit", "-q", "-m", "stalled", "-m", "Sdlc-Ticket: T-042-02"], cwd=self.p.root,
                       check=True, env=git_env(GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old))
        git(self.p.root, "checkout", "-q", "main")
        self.assertEqual(self.p.sdlc("status", "T-042-02")[1].strip(), "ready")
        self.assertIn("T-042-02\tready\texpired claim on someone-else\t", self.p.sdlc("status")[1])
        self.assertEqual(self.p.sdlc("next")[1].strip(), "T-042-02")
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertEqual(code, 0, out)
        git(self.p.root, "checkout", "-q", "someone-else")
        git(self.p.root, "commit", "-q", "--allow-empty", "-m", "back on it")  # a new commit renews it
        git(self.p.root, "checkout", "-q", "main")
        self.assertIn("T-042-02\tin_progress\ton someone-else\t", self.p.sdlc("status")[1])
        code, out = self.p.sdlc("run", "build", "T-042-02", "--agent", "fake", "--dry-run")
        self.assertIn("T-042-02 is in progress on someone-else", out)

    def test_doctor_rejects_bad_claim_settings(self) -> None:
        for bad, msg in (('claim = "lock"', "vcs.claim = 'lock'"), ('claim = "push"\nclaim_days = -1', "vcs.claim_days = -1"),
                         ('claim = "push"\nclaim_days = true', "vcs.claim_days = True")):
            self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('claim = "push"', bad, 1))
            code, out = self.p.sdlc("doctor")
            self.assertNotEqual(code, 0, out)
            self.assertIn(msg, out)
            git(self.p.root, "checkout", "-q", "--", "sdlc.toml")
        self.assertIn("claim push", self.p.sdlc("doctor")[1])

    def test_status_prs_shows_an_open_pr_from_the_building_branch(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")

        class Pulls:
            repo = "owner/product"

            def pages(self, path):
                assert path == "/pulls?state=open", path
                return [{"number": 12, "head": {"ref": "build/T-042-02", "repo": {"full_name": "owner/product"}}},
                        {"number": 13, "head": {"ref": "build/T-042-02", "repo": {"full_name": "fork/product"}}}]

        self.fake = Pulls()
        code, out = self.p.sdlc("status", "--prs")
        self.assertIn("T-042-02\tin_progress\ton build/T-042-02; in review: PR #12\t", out)
        self.assertNotIn("PR #13", out)                              # a fork's branch of the same name
        self.assertNotIn("PR #12", self.p.sdlc("status")[1])         # opt-in: no network without --prs
        row = json.loads(self.p.sdlc("status", "T-042-02", "--json", "--prs")[1])
        self.assertEqual(row["prs"], [12])


    def test_status_prs_warns_and_shows_none_when_the_lookup_fails(self) -> None:
        self.build()
        git(self.p.root, "checkout", "-q", "main")

        class Down:
            repo = "owner/product"

            def pages(self, path):
                raise OSError("network unreachable")

        self.fake = Down()
        code, out = self.p.sdlc("status", "--prs")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN --prs: could not list open PRs: network unreachable", out)
        self.assertIn("T-042-02\tin_progress\ton build/T-042-02\t", out)

    def test_status_prs_shows_an_open_pr_from_an_expired_branch(self) -> None:
        from helpers import git_env

        self.p.write("sdlc.toml", self.p.read("sdlc.toml").replace('claim = "push"', 'claim = "local"\nclaim_days = 3'))
        self.p.commit("lead: claims expire")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        old = "2026-01-01T00:00:00Z"
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "stalled", "-m", "Sdlc-Ticket: T-042-02"],
                       cwd=self.p.root, check=True, env=git_env(GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old))
        git(self.p.root, "checkout", "-q", "main")

        class Pulls:
            repo = "owner/product"

            def pages(self, path):
                return [{"number": 12, "head": {"ref": "build/T-042-02", "repo": {"full_name": "owner/product"}}}]

        self.fake = Pulls()
        out = self.p.sdlc("status", "--prs")[1]
        self.assertIn("T-042-02\tready\tin review: PR #12; expired claim on build/T-042-02\t", out)

if __name__ == "__main__":
    unittest.main()
