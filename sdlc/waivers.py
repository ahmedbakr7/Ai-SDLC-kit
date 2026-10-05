"""Waivers (ADR-0002 step 4b): explicit, owned, dated exceptions for a failure the base branch
already has and cannot fix yet, listed in sdlc-waivers.toml by the lead.

    [[waiver]]
    id = "W-1"
    check = "unit"
    key = "tests/vendor.test.ts > flaky upstream"
    count = 1
    owner = "lead"
    reason = "vendor sandbox down until the 20th"
    expires = 2026-11-01
    ticket = "T-042-07"      # optional: the follow-up that removes it
    renews = "W-0"           # optional: the waiver this one renews (removed in the same change)

A waiver applies only once it is on the base branch, unchanged: a branch that adds one, or
raises its count, is judged without it, so a PR cannot waive its own new failure. Up to
`count` occurrences of its key pass as WAIVED; more fail. Its creation date is the committer
date of the base branch's first-parent commit that introduced it, never a typed field. It
lasts at most `[waivers] max_days` (90) from that date, and a chain of renewals at most twice
that from the first entry's date. `gate ci` fails on an expired, stale or invalid waiver;
ticket gates only report one. Process checks are never waivable."""
from __future__ import annotations

import datetime as dt
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import baseline, gitutil

DEFAULT_PATH = "sdlc-waivers.toml"
DEFAULT_MAX_DAYS = 90
WARN_DAYS = 14
# They judge the change, not the code it starts from (the baseline excludes them too).
NEVER = ("scope", "immutable", "review-file", "approval", "mechanical", "spike", "contract-diff", "ac-red",
         "skills")
REQUIRED = ("id", "check", "key", "count", "owner", "reason", "expires")
OPTIONAL = ("ticket", "renews")


@dataclass
class Waiver:
    id: str
    check: str
    key: str
    count: int
    owner: str
    reason: str
    expires: dt.date
    ticket: str = ""
    renews: str = ""
    created: dt.date | None = None   # from the base branch's history; None: not on the base yet
    origin: dt.date | None = None    # the creation date of the first entry in its renewal chain
    renewed_by: str = ""             # the branch's renewal that replaces it (its expiry is judged)

    def label(self) -> str:
        return f"{self.id} (owner {self.owner}, expires {self.expires.isoformat()})"


@dataclass
class State:
    """The waivers a gate applies, and what is wrong with the file."""
    active: list[Waiver] = field(default_factory=list)   # on the base branch, unchanged
    pending: list[str] = field(default_factory=list)     # ids the branch adds or changes
    problems: list[str] = field(default_factory=list)    # fail `gate ci`
    warnings: list[str] = field(default_factory=list)    # reported only

    def for_check(self, name: str) -> list[Waiver]:
        return [w for w in self.active if w.check == name]


def path(root: Path, cfg_paths: dict) -> Path:
    return root / cfg_paths.get("waivers", DEFAULT_PATH)


def max_days(cfg_section: dict) -> int:
    n = cfg_section.get("max_days", DEFAULT_MAX_DAYS)
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else DEFAULT_MAX_DAYS


def parse(text: str | None) -> tuple[list[dict], list[str]]:
    """(entries, problems). An entry with a problem is left out: it waives nothing."""
    if not text:
        return [], []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return [], [f"not valid TOML: {e}"]
    raw = data.get("waiver", [])
    if not isinstance(raw, list):
        return [], ["`waiver` must be an array of tables ([[waiver]])"]
    out, probs, seen = [], [], set()
    for i, w in enumerate(raw, 1):
        where = f"waiver #{i}" + (f" ({w.get('id')})" if isinstance(w, dict) and w.get("id") else "")
        if not isinstance(w, dict):
            probs.append(f"{where}: not a table")
            continue
        bad = [k for k in REQUIRED if k not in w] + [f"unknown field {k!r}" for k in w if k not in REQUIRED + OPTIONAL]
        if bad:
            probs.append(f"{where}: " + ", ".join(b if b.startswith("unknown") else f"missing {b!r}" for b in bad))
            continue
        if not all(isinstance(w[k], str) and w[k].strip() for k in ("id", "check", "key", "owner", "reason")):
            probs.append(f"{where}: id, check, key, owner and reason must be non-empty strings")
            continue
        if not all(isinstance(w.get(k, ""), str) for k in OPTIONAL):
            probs.append(f"{where}: ticket and renews must be strings")
            continue
        n = w["count"]
        if not isinstance(n, int) or isinstance(n, bool) or not 0 < n <= baseline.MAX_COUNT:
            probs.append(f"{where}: count must be an integer from 1 to {baseline.MAX_COUNT}")
            continue
        if not isinstance(w["expires"], dt.date) or isinstance(w["expires"], dt.datetime):
            probs.append(f"{where}: expires must be a date (expires = 2026-11-01)")
            continue
        if w["check"] in NEVER:
            probs.append(f"{where}: {w['check']} is never waivable: it judges the change, not the code it starts from")
            continue
        if w["check"] not in baseline.BASELINE_CHECKS:
            probs.append(f"{where}: unknown check {w['check']!r} (waivable: {', '.join(baseline.BASELINE_CHECKS)})")
            continue
        if w["id"] in seen:
            probs.append(f"{where}: duplicate id")
            continue
        seen.add(w["id"])
        out.append(w)
    return out, probs


def _waiver(w: dict) -> Waiver:
    return Waiver(w["id"], w["check"], w["key"], w["count"], w["owner"], w["reason"], w["expires"],
                  w.get("ticket", ""), w.get("renews", ""))


def history(root: Path, rel: str, ref: str) -> tuple[dict[str, tuple[dict, dt.datetime]], list[str]]:
    """id -> (entry as first seen, committer date of the first-parent commit on `ref` that
    introduced it), across the file's whole first-parent history, plus problems with those
    dates: a commit dated before its first parent, or in the future."""
    out = gitutil.git(root, "log", "--first-parent", "--reverse", "--format=%H %ct %P", ref, "--", rel, check=False)
    seen: dict[str, tuple[dict, dt.datetime]] = {}
    probs: list[str] = []
    now = dt.datetime.now(dt.timezone.utc)
    for line in out.splitlines():
        sha, ct, *parents = line.split()
        when = dt.datetime.fromtimestamp(int(ct), dt.timezone.utc)
        entries, _ = parse(gitutil.show(root, sha, "./" + rel))
        fresh = [e for e in entries if e["id"] not in seen]
        if not fresh:
            continue
        if when > now:
            probs.append(f"{sha[:12]} introduces {', '.join(e['id'] for e in fresh)} dated in the future ({when:%Y-%m-%d})")
        if parents:
            pct = gitutil.git(root, "log", "-1", "--format=%ct", parents[0], check=False).strip()
            if pct and int(pct) > int(ct):
                probs.append(f"{sha[:12]} introduces {', '.join(e['id'] for e in fresh)} dated before its parent "
                             f"{parents[0][:12]}: the date cannot be trusted")
        for e in fresh:
            seen[e["id"]] = (e, when)
    return seen, probs


def state(root: Path, rel: str, base_ref: str | None, days: int, today: dt.date | None = None) -> State:
    """The waivers that apply to a gate run on the working tree against `base_ref` (the merge
    base, or HEAD on the base branch itself). Without a base nothing applies."""
    today = today or dt.date.today()
    s = State()
    f = root / rel
    branch_entries, probs = parse(f.read_text(encoding="utf-8") if f.is_file() else None)
    s.problems += [f"{rel}: {p}" for p in probs]
    if base_ref is None:
        s.pending = [e["id"] for e in branch_entries]
        return s
    base_entries, _ = parse(gitutil.show(root, base_ref, "./" + rel))
    seen, date_probs = history(root, rel, base_ref)
    s.problems += [f"{rel}: {p}" for p in date_probs]
    by_branch = {e["id"]: e for e in branch_entries}
    by_base = {e["id"]: e for e in base_entries}

    def dated(w: Waiver) -> Waiver:
        if w.id in seen:
            w.created = seen[w.id][1].date()
        origin, cur, hops = w.created, w, 0
        while cur.renews and cur.renews in seen and hops < 100:
            prev, when = seen[cur.renews]
            origin, cur, hops = when.date(), _waiver(prev), hops + 1
        w.origin = origin
        return w

    for wid, e in by_base.items():
        if by_branch.get(wid) == e:
            s.active.append(dated(_waiver(e)))
    for wid, e in by_branch.items():
        if by_base.get(wid) == e:
            continue
        s.pending.append(wid)
        old = by_base.get(e.get("renews", ""))
        # A renewal keeps the renewed waiver's coverage in its own PR, never more of it.
        if old and old["id"] not in by_branch and (old["check"], old["key"]) == (e["check"], e["key"]):
            kept = dated(_waiver(old))
            kept.count, kept.renewed_by = min(kept.count, e["count"]), wid
            s.active.append(kept)
    for w in s.active:
        _judge(w, days, today, s)
    for wid in s.pending:
        e = by_branch[wid]
        w = _waiver(e)
        if w.expires > today + dt.timedelta(days=days):
            s.problems.append(f"{rel}: {wid} expires {w.expires}, more than {days} days from today")
        if w.renews and w.renews in by_branch:
            s.problems.append(f"{rel}: {wid} renews {w.renews}, which must be removed in the same change")
        root_date = dated(_waiver(e)).origin if w.renews else None
        if root_date and w.expires > root_date + dt.timedelta(days=2 * days):
            s.problems.append(f"{rel}: {wid} would make its renewal chain last past {2 * days} days from "
                              f"{root_date}; fix the failure, or move it into the baseline in a lead PR")
    return s


def _judge(w: Waiver, days: int, today: dt.date, s: State) -> None:
    if w.created is None:  # on the base branch, so its history must show it (fetch-depth: 0)
        s.problems.append(f"{w.id}: no commit on the base branch's first-parent history introduces it; "
                          "its age cannot be checked (a shallow clone?)")
    if w.created and w.expires > w.created + dt.timedelta(days=days):
        s.problems.append(f"{w.id}: expires {w.expires}, more than {days} days after it was added on {w.created}")
    if w.origin and w.expires > w.origin + dt.timedelta(days=2 * days):
        s.problems.append(f"{w.id}: its renewal chain lasts past {2 * days} days from {w.origin}; fix the failure, "
                          "or move it into the baseline in a lead PR")
    if w.renewed_by:
        return  # the renewal in this change is judged instead
    if w.expires < today:
        s.problems.append(f"{w.id}: expired on {w.expires} (owner {w.owner}: {w.reason})")
    elif w.expires <= today + dt.timedelta(days=WARN_DAYS):
        s.warnings.append(f"{w.id}: expires on {w.expires}, in {(w.expires - today).days} day(s) "
                          f"(owner {w.owner}); renew it or fix the failure")


def apply(waivers: list[Waiver], new: list[str]) -> tuple[list[str], list[tuple[str, Waiver]], list[Waiver]]:
    """(still new, [(key, waiver)] covered, waivers that covered nothing). Each waiver covers
    at most `count` occurrences of its key; the rest stay new."""
    left = Counter(new)
    covered: list[tuple[str, Waiver]] = []
    unused: list[Waiver] = []
    for w in waivers:
        n = min(left[w.key], w.count)
        if n == 0:
            unused.append(w)
            continue
        left[w.key] -= n
        covered += [(w.key, w)] * n
    return sorted(left.elements()), covered, unused
