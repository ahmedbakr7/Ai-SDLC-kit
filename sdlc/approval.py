"""Approvals bound to the PR's own diff (ADR-0001 section 4).

An approval is a record {reviewed sha, identity, role, verdict, reviewer agent, body}. It is
never committed to the tree. It lives in the forge (a PR review, or a PR comment carrying the
record's front matter) or, in plain git, in a note on the reviewed commit (refs/notes/sdlc).

It covers the current head when the PR's own change is the same, location-exact
(gitutil.covers): a base merge keeps it; an edit, a move or a conflict resolution voids it.

Who gave it is checked against [approval] reviewers / leads / bots, and a standard or strict
approval must come from an identity that neither opened the PR nor authored its commits.
With one identity for everyone that cannot hold, so the check fails closed, unless the lead
sets [approval] trust_unsigned = true: then declared roles are accepted from identities with
write access, and every result says the approval layer is trust-based.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field

from . import fm, gitutil, presets
from .config import Config

MODES = ("file", "forge", "git")
ROLES = ("review", "lead", "bot")
VERDICTS = ("approve", "request_changes")
NOTES_REF = "refs/notes/sdlc"


def mode(cfg: Config) -> str:
    m = str(cfg.section("approval").get("mode", "file"))
    return m if m in MODES else "file"


def records_mode(cfg: Config) -> bool:
    """Approvals live outside the tree (forge or git): evidence stays in CI, status is derived."""
    return mode(cfg) != "file"


@dataclass
class Record:
    sha: str                 # the reviewed commit
    who: str                 # forge login, or signer / committer in git mode
    role: str                # review | lead | bot
    verdict: str             # approve | request_changes
    agent: str = ""          # the reviewing agent's name (front matter `reviewer:`)
    body: str = ""
    source: str = ""         # review | comment | note
    association: str = ""    # forge author_association
    signed: bool = False     # git mode: a good signature from an allowed signer
    at: str = ""             # when it was given (orders a reviewer's records)
    ticket: str = ""


def render(ticket: str, sha: str, verdict: str, role: str, reviewer: str, body: str) -> str:
    """The text of a record, as `sdlc review publish` posts it."""
    head = (f"---\nsdlc: approval\nticket: {ticket}\ncommit: {sha}\nverdict: {verdict}\nrole: {role}\n"
            f"reviewer: {reviewer}\n---\n")
    return head + body.lstrip("\n")


def parse(text: str) -> dict | None:
    """The front matter of a record, or None when `text` is not one."""
    text = (text or "").replace("\r\n", "\n").lstrip()
    head, body, _ = fm.split(text)
    if head is None:
        return None
    try:
        d = fm.parse(head)
    except fm.ParseError:
        return None
    if str(d.get("sdlc", "")) != "approval":
        return None
    d["_body"] = body
    return d


def _from_text(text: str, **kw) -> Record | None:
    d = parse(text)
    if d is None:
        return None
    return Record(sha=str(d.get("commit", "")), role=str(d.get("role", "review")), verdict=str(d.get("verdict", "")),
                  agent=str(d.get("reviewer", "")), body=str(d["_body"]), ticket=str(d.get("ticket", "")), **kw)


# -- forge (GitHub REST, stdlib) ------------------------------------------------
class GitHub:
    def __init__(self, repo: str, token: str = "", api: str = "https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api.rstrip("/")

    def _req(self, method: str, path: str, data: dict | None = None):
        req = urllib.request.Request(f"{self.api}/repos/{self.repo}{path}", method=method,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28",
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                                              **({"Content-Type": "application/json"} if data is not None else {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8") or "null")

    def get(self, path: str):
        return self._req("GET", path)

    def pages(self, path: str) -> list:
        out, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            got = self.get(f"{path}{sep}per_page=100&page={page}") or []
            out += got
            if len(got) < 100:
                return out
            page += 1

    def post(self, path: str, data: dict):
        return self._req("POST", path, data)


def forge_client(cfg: Config | None) -> GitHub:
    """A client carrying the forge token. The API host comes from the environment only
    (GITHUB_API_URL, which Actions sets), never from an sdlc.toml: a branch's sdlc.toml is
    the PR's to write and must not decide where the token goes. `cfg` None: the repository too
    comes from the environment, for the lookup made before the base branch is known."""
    a = cfg.section("approval") if cfg is not None else {}
    repo = str(a.get("repo") or os.environ.get("GITHUB_REPOSITORY", ""))
    if not repo:
        raise SystemExit("approval: set [approval] repo = \"owner/name\" or GITHUB_REPOSITORY")
    token = os.environ.get("SDLC_FORGE_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    return GitHub(repo, token, os.environ.get("GITHUB_API_URL") or "https://api.github.com")


def pr_number(given: int | None = None) -> int | None:
    """--pr, else the PR of the GitHub event this job runs for."""
    if given:
        return given
    p = os.environ.get("GITHUB_EVENT_PATH")
    if p and os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            ev = json.load(f)
        n = (ev.get("pull_request") or {}).get("number") or (ev.get("issue") or {}).get("number")
        return int(n) if n else None
    return None


@dataclass
class PullRequest:
    number: int
    author: str
    head: str
    commit_authors: set[str] = field(default_factory=set)
    base: str = ""                                          # the branch the PR targets
    permissions: dict[str, str] = field(default_factory=dict)  # login -> repo permission


REVIEW_STATES = {"APPROVED": "approve", "CHANGES_REQUESTED": "request_changes", "COMMENTED": ""}


def forge_records(client: GitHub, n: int) -> tuple[PullRequest, list[Record]]:
    pr = client.get(f"/pulls/{n}")
    info = PullRequest(n, (pr.get("user") or {}).get("login", ""), (pr.get("head") or {}).get("sha", ""),
                       base=(pr.get("base") or {}).get("ref", ""))
    for c in client.pages(f"/pulls/{n}/commits"):
        for k in ("author", "committer"):
            login = (c.get(k) or {}).get("login")
            if login and login != "web-flow":
                info.commit_authors.add(login)
    out: list[Record] = []
    for rv in client.pages(f"/pulls/{n}/reviews"):
        state = rv.get("state", "")
        if state not in REVIEW_STATES:
            continue  # DISMISSED and PENDING reviews approve nothing
        who, assoc, sha = (rv.get("user") or {}).get("login", ""), rv.get("author_association", ""), rv.get("commit_id") or ""
        rec = _from_text(rv.get("body") or "", who=who, source="review", association=assoc,
                         at=rv.get("submitted_at") or "")
        if rec is not None:
            # A review is bound to the commit the forge says it was given on, and its state
            # must agree with the record: the body can be edited, the commit and state cannot.
            # A COMMENTED review is no verdict at all (publish records as PR comments instead).
            if rec.sha != sha or REVIEW_STATES[state] != rec.verdict:
                continue
        elif REVIEW_STATES[state]:
            rec = Record(sha=sha, who=who, role="", source="review", association=assoc, verdict=REVIEW_STATES[state],
                         body=rv.get("body") or "", at=rv.get("submitted_at") or "")
        if rec is not None:
            out.append(rec)
    for cm in client.pages(f"/issues/{n}/comments"):
        if cm.get("updated_at") and cm.get("updated_at") != cm.get("created_at"):
            continue  # an edited comment may say what its author never wrote (others with write access can edit)
        rec = _from_text(cm.get("body") or "", who=(cm.get("user") or {}).get("login", ""), source="comment",
                         association=cm.get("author_association", ""), at=cm.get("created_at") or "")
        if rec is not None:
            out.append(rec)
    # author_association is not a permission (MEMBER and COLLABORATOR include read-only); ask.
    for who in sorted({r.who for r in out if r.who}):
        try:
            info.permissions[who] = str((client.get(f"/collaborators/{who}/permission") or {}).get("permission", ""))
        except Exception:
            info.permissions[who] = ""
    return info, out


# -- plain git (notes) ----------------------------------------------------------
def signers_file(cfg: Config, base: str) -> str:
    """The allowed-signers file as the base branch has it (a temp copy), or an absolute path
    outside the tree: a PR must not choose who may sign its approvals."""
    import tempfile

    rel = str(cfg.section("approval").get("allowed_signers", ""))
    if not rel:
        return ""
    if os.path.isabs(rel):
        return rel
    try:
        mb = gitutil.merge_base(cfg.root, base)
    except gitutil.GitError:
        return ""
    data = gitutil.show_bytes(cfg.root, mb, "./" + rel)
    if data is None:
        return ""
    fd, path = tempfile.mkstemp(prefix="sdlc-signers-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def git_records(cfg: Config, shas: list[str], base: str = "main") -> list[Record]:
    """Notes on the PR's commits in refs/notes/sdlc. A note's identity is the signer of the
    notes commit that wrote it (checked against the base branch's allowed signers), else its
    committer."""
    root = cfg.root
    signers = signers_file(cfg, base)
    paths = {p.replace("/", ""): p for p in
             gitutil.git(root, "ls-tree", "-r", "--name-only", NOTES_REF, check=False).split()}
    out = []
    try:
        return _notes(cfg, shas, paths, signers, out)
    finally:
        rel = str(cfg.section("approval").get("allowed_signers", ""))
        if signers and not os.path.isabs(rel):
            os.unlink(signers)


def _notes(cfg: Config, shas: list[str], paths: dict[str, str], signers: str, out: list[Record]) -> list[Record]:
    root = cfg.root
    for sha in shas:
        path = paths.get(sha)
        if not path:
            continue
        text = gitutil.git(root, "notes", "--ref", NOTES_REF, "show", sha, check=False)
        cfg_args = ["-c", f"gpg.ssh.allowedSignersFile={signers}"] if signers else []
        # The notes commit that last wrote this note decides who gave it.
        line = gitutil.git(root, *cfg_args, "log", "-1", "--format=%G?%x00%GS%x00%ce%x00%ct", NOTES_REF,
                           "--", path, check=False).strip()
        status, signer, email, at = (line.split("\0") + ["", "", "", ""])[:4]
        signed = status == "G" and bool(signer)
        rec = _from_text(text, who=signer if signed else email, source="note", signed=signed, at=at.zfill(12))
        if rec is not None:
            rec.sha = rec.sha or sha
            out.append(rec)
    return out


def commit_identities(cfg: Config, base: str, head: str) -> set[str]:
    """Author and committer emails and names of the PR's commits (git mode's independence check)."""
    try:
        mb = gitutil.merge_base(cfg.root, base, head)
    except gitutil.GitError:
        return set()
    out = gitutil.git(cfg.root, "log", f"{mb}..{head}", "--format=%ae%n%ce%n%an%n%cn", check=False)
    return {x.strip() for x in out.splitlines() if x.strip()}


def notes_missing(cfg: Config) -> bool:
    return not gitutil.git(cfg.root, "rev-parse", "--verify", "-q", NOTES_REF, check=False).strip()


# -- evaluation -----------------------------------------------------------------
@dataclass
class Result:
    ok: bool
    summary: str
    details: list[str] = field(default_factory=list)
    trust_based: bool = False


def required_roles(lane: str, lead_amendments: list[str], human_review: bool = False) -> list[str]:
    """Roles a ticket PR needs. A mechanical PR takes any reviewer or bot, unless the hardened
    preset asks for a human reviewer (`human_review`)."""
    need = ["review"] if lane != "mechanical" or human_review else ["any"]
    if lane == "strict" or lead_amendments:
        need.append("lead")
    return need


def identity_problems(cfg: Config, rec: Record, role: str, pr: PullRequest | None, build_agents: set[str],
                      committers: set[str] | None = None) -> list[str]:
    """Why `rec` cannot count for `role` (empty: it counts)."""
    a = cfg.section("approval")
    trust = bool(a.get("trust_unsigned", False))
    out = []
    if role in ("review", "lead") and rec.agent and rec.agent in build_agents:
        out.append(f"reviewer {rec.agent} also built this change (Sdlc-Agent trailer)")
    if rec.source == "note":
        if not rec.signed and not trust:
            out.append("unsigned note (set [approval] allowed_signers, or trust_unsigned for trust-based approvals)")
        if rec.signed and not trust:
            if rec.who not in _list(cfg, role):
                out.append(f"signer {rec.who} is not in [approval] {_key(role)}")
            if role in ("review", "lead") and rec.who in (committers or set()):
                out.append(f"signer {rec.who} authored or committed this PR's commits")
        return out
    if trust:
        # Trust-based (the lead's explicit choice for one shared identity): declared roles are
        # taken on trust, so the author exclusions cannot apply; write access is still required,
        # because on a public repository anyone can comment.
        perm = (pr.permissions.get(rec.who, "") if pr is not None else "")
        if perm not in ("admin", "maintain", "write"):
            out.append(f"{rec.who} has no write access ({perm or rec.association or 'unknown'})")
        return out
    if rec.who not in _list(cfg, role):
        out.append(f"{rec.who} is not in [approval] {_key(role)}")
    if role in ("review", "lead") and pr is not None:
        if rec.who == pr.author:
            out.append(f"{rec.who} opened this PR")
        elif rec.who in pr.commit_authors:
            out.append(f"{rec.who} authored commits in this PR")
    return out


def _key(role: str) -> str:
    return {"review": "reviewers", "lead": "leads", "bot": "bots"}[role]


def latest(cfg: Config, records: list[Record]) -> list[tuple[Record, str]]:
    """Each identity's newest record per role, roles resolved first (a native review takes its
    roles from the allowlists): a later request_changes withdraws an earlier approval."""
    keep: dict[tuple[str, str], Record] = {}
    for r in sorted(records, key=lambda r: r.at):
        roles = [r.role] if r.role in ROLES else [x for x in ROLES if r.who in _list(cfg, x)]
        for role in roles:
            keep[(r.who, role)] = r
    return [(r, role) for (_, role), r in keep.items()]


def lead_amendments(cfg: Config, base: str) -> list[str]:
    """New `weaken` / `remove` lines in any ticket the branch changes: each needs a lead,
    whichever ticket (if any) the PR says it serves."""
    from .artifacts import Repo
    from .tickets import new_amendments

    try:
        mb = gitutil.merge_base(cfg.root, base)
    except gitutil.GitError:
        return []
    repo = Repo(cfg)
    out = []
    changed = set(gitutil.changed_files(cfg.root, base))
    for t in repo.tickets.values():
        rel = cfg.rel(t.path)
        if rel not in changed:
            continue
        old = fm.split(gitutil.show(cfg.root, mb, "./" + rel) or "")[1]
        out += [f"{t.id}: {k} {target}" for k, target, _ in new_amendments(old, t.body)[0] if k in ("weaken", "remove")]
    return out


def evaluate(cfg: Config, gate, records: list[Record], pr: PullRequest | None, head: str) -> Result:
    """Does an approval cover `head` for every role the lane needs? `gate` is a Gate for the
    `pr` play: it knows the ticket, the lane, the out-of-area files and the new amendments."""
    from .gate import _review_entries, _glob

    trust = bool(cfg.section("approval").get("trust_unsigned", False))
    t = gate.ticket
    lead_lines = lead_amendments(cfg, gate.base)
    if t is None:
        # A PR naming no ticket is the lead's, and the lead approves it: it can change config,
        # CI, the kit pin, contracts or tickets, all of which govern every later PR.
        changed = gitutil.changed_files(cfg.root, gate.base)
        if not changed:
            return Result(True, "nothing changed", trust_based=trust)
        need, lane, amendments = ["lead"], "lead PR", []
        lead_lines = lead_lines or [f"a PR without a ticket ({len(changed)} file(s))"]
    else:
        lane = gate.lane.name if gate.lane else "standard"
        amendments = gate.new_amendments()
        need = required_roles(lane, lead_lines, human_review=presets.hardened(cfg.data))
    build_agents = _build_agents(cfg, gate.base, head)
    # The independent-reviewer rule compares the record's agent with the agents named in the
    # branch's Sdlc-Agent trailers; a commit that names none would make any agent look independent.
    unnamed = _commits_without_agent(cfg, gate.base, head) if t is not None else []
    committers = commit_identities(cfg, gate.base, head) if mode(cfg) == "git" else set()
    flagged = gate.out_of_area() if t is not None else []
    details, granted = [], {}
    for rec, role in latest(cfg, records):
        if rec.verdict not in VERDICTS or (rec.ticket and t is not None and rec.ticket != t.id):
            continue
        why = identity_problems(cfg, rec, role, pr, build_agents, committers)
        stale = gitutil.covers(cfg.root, gate.base, rec.sha, head) if rec.sha else ["no reviewed commit"]
        content = (_content_problems(rec, role, t, lane, flagged, amendments, _review_entries, _glob)
                   if t is not None else [])
        label = f"{role} {rec.verdict} by {rec.who}" + (f" ({rec.agent})" if rec.agent else "") + f" at {rec.sha[:12]}"
        if why or stale or content:
            details.append(f"{label}: does not count: " + "; ".join(why + stale[:3] + content[:5]))
            continue
        details.append(f"{label}: counts")
        granted.setdefault(role, []).append(rec)
    for rec in records:
        if not (rec.role in ROLES or any(rec.who in _list(cfg, x) for x in ROLES)):
            details.append(f"{rec.source} by {rec.who}: no role (declare role:, or list the identity in [approval])")
    missing = []
    if unnamed:
        missing.append(f"Sdlc-Agent trailers on {len(unnamed)} commit(s) ({', '.join(s[:7] for s in unnamed[:5])}) "
                       "to check reviewer independence")
    approvers ={role: {r.who for r in rs if r.verdict == "approve"} for role, rs in granted.items()}
    for role in need:
        if role == "any":
            if not any(approvers.values()):
                missing.append("an approving review (any reviewer or bot)")
            continue
        rs = granted.get(role, [])
        if any(r.verdict == "request_changes" for r in rs):
            missing.append(f"{role}: changes requested")
        elif not approvers.get(role):
            missing.append({"review": "an approval from an independent reviewer",
                            "lead": "a lead approval" + (f" (for {', '.join(lead_lines)})" if lead_lines else
                                                         " (strict lane)")}[role])
    if "review" in need and "lead" in need and not missing and not trust:
        # Two roles are two people: one identity listed as both does not sign off alone.
        if not any(a != b for a in approvers.get("review", set()) for b in approvers.get("lead", set())):
            missing.append("the review and the lead approval from different identities")
    # The label leads: a status description keeps only 140 characters.
    label = "[trust-based: identities not verified] " if trust else ""
    who = t.id if t is not None else "this PR"
    if missing:
        return Result(False, f"{label}{who} ({lane}) needs " + "; ".join(missing), details, trust)
    return Result(True, f"{label}{who} ({lane}) approved for {head[:12]}", details, trust)


def _list(cfg: Config, role: str) -> list[str]:
    return [str(x) for x in cfg.section("approval").get({"review": "reviewers", "lead": "leads", "bot": "bots"}[role], [])]


def _commits_without_agent(cfg: Config, base: str, head: str) -> list[str]:
    """The branch's own non-merge commits (oldest first) that carry no Sdlc-Agent trailer."""
    try:
        mb = gitutil.merge_base(cfg.root, base, head)
    except gitutil.GitError:
        return []
    log = gitutil.git(cfg.root, "log", "--reverse", "--no-merges", f"{mb}..{head}",
                      "--format=%H|%(trailers:key=Sdlc-Agent,valueonly,separator=%x2C)", check=False)
    return [sha for sha, _, agent in (line.partition("|") for line in log.splitlines()) if sha and not agent.strip()]


def _build_agents(cfg: Config, base: str, head: str) -> set[str]:
    """Agents with a non-review commit on the branch (Sdlc-Agent / Sdlc-Play trailers)."""
    try:
        mb = gitutil.merge_base(cfg.root, base, head)
    except gitutil.GitError:
        return set()
    return gitutil.build_agents(cfg.root, f"{mb}..{head}")


def _content_problems(rec: Record, role: str, t, lane: str, flagged: list[str], amendments, review_entries, glob) -> list[str]:
    """An approving record names what the reviewer judged: one AC row per AC (above the
    mechanical lane), each out-of-area file, each strengthen/split/widen amendment."""
    if rec.verdict != "approve" or role != "review":
        return []  # a lead's sign-off or a bot's review is not the independent review
    body = rec.body or ""
    out = []
    if lane != "mechanical":
        rows = {m.group(1) for m in re.finditer(r"^\|\s*(AC-\d+)\s*\|", body, re.M)}
        out += [f"no AC row for {ac}" for ac, _ in t.acs if ac and ac not in rows]
    named = review_entries(body, "## Out of area")
    out += [f"out of area and not named: {f}" for f in flagged if not any(f == e or glob(f, e) for e in named)]
    judged = set(review_entries(body, "## Amendments"))
    out += [f"amendment `{k} {target}` not named under ## Amendments" for k, target, _ in amendments
            if k in ("strengthen", "split", "widen", "weaken", "remove") and target.split()[0] not in judged]
    return out
