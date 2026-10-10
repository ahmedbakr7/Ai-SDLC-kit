"""Thin git helpers (subprocess, no libraries)."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def _paths(out: str) -> list[str]:
    """Pathnames from NUL-delimited git output, verbatim: "a.md " is not "a.md", and
    non-ASCII names are not quoted."""
    return [n for n in out.split("\0") if n]


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD", check=False).strip() or "(no commits)"


def is_dirty(root: Path) -> bool:
    return bool(git(root, "status", "--porcelain", check=False).strip())


def merge_base(root: Path, base: str, ref: str = "HEAD") -> str:
    for b in (base, f"origin/{base}"):
        out = git(root, "merge-base", ref, b, check=False).strip()
        if out:
            return out
    raise GitError(f"cannot find merge base with {base!r} (fetch it, or pass --base)")


def changed_files(root: Path, base: str) -> list[str]:
    """Files changed vs merge-base(HEAD, base), including staged, unstaged and untracked."""
    mb = merge_base(root, base)
    # --relative / ls-files: paths relative to the product root, so a product nested
    # in a monorepo only sees (and is only judged on) its own files.
    names = set(_paths(git(root, "diff", "--name-only", "-z", "--no-renames", "--relative", mb)))
    names |= set(_paths(git(root, "ls-files", "--others", "--exclude-standard", "-z")))
    return sorted(names)


def build_agents(root: Path, revs: str) -> set[str]:
    """Agents named by the Sdlc-Agent trailers of commits in `revs` that are not review-only.
    Each repeated trailer is its own agent: joined, "other" and "builder" would read as one
    agent "other,builder", and the builder would look independent of its own commit."""
    # NUL separates the two fields and (-z) the commits: git refuses a NUL in a commit message,
    # so no value can shift one field into the next. Repeated trailers are joined with US.
    log = git(root, "log", "-z", revs, "--format=%(trailers:key=Sdlc-Agent,valueonly,unfold,separator=%x1F)%x00"
              "%(trailers:key=Sdlc-Play,valueonly,unfold,separator=%x1F)", check=False)
    fields = log.split("\0")
    out: set[str] = set()
    for agents, plays in zip(fields[0::2], fields[1::2]):
        if {p.strip() for p in plays.split("\x1f")} != {"review"}:
            out |= {a.strip() for a in agents.split("\x1f") if a.strip()}
    return out


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=root,
                          capture_output=True).returncode == 0


def show_bytes(root: Path, ref: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def show(root: Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def committed_between(root: Path, a: str, b: str = "HEAD") -> list[str]:
    """Files whose committed content differs between `a` and `b` (untracked files excluded)."""
    return sorted(_paths(git(root, "diff", "--name-only", "-z", "--no-renames", "--relative", a, b)))


def untracked(root: Path) -> list[str]:
    return _paths(git(root, "ls-files", "--others", "--exclude-standard", "-z"))


def changed_since(root: Path, ref: str) -> list[str]:
    """Files changed after commit `ref` (committed or not)."""
    names = set(_paths(git(root, "diff", "--name-only", "-z", "--no-renames", "--relative", ref)))
    names |= set(untracked(root))
    return sorted(names)


def same_branch_change(root: Path, base: str, then: str, path: str, now: str | None = None) -> bool:
    """`path` at `now` (the working tree when None) is exactly the file at commit `then` with
    the base branch's later changes merged in: replaying main's change from the old merge
    base to the new one onto `then`'s version merges cleanly and gives the same blob.
    Location-exact, so moving a reviewed line counts. False when no base merge happened in
    between, when the file is missing on a side, or when the replay conflicts."""
    mb_then = merge_base(root, base, then)
    mb_now = merge_base(root, base, now or "HEAD")
    if mb_then == mb_now:
        return False
    ours, old, theirs = (show_bytes(root, ref, "./" + path) for ref in (then, mb_then, mb_now))
    if ours is None or old is None or theirs is None:
        return False
    if now is None:
        # The blob the working-tree file would be stored as (git's own filters, such as autocrlf).
        if not (root / path).is_file():
            return False
        current = git(root, "hash-object", "--", path).strip()
    else:
        current = git(root, "rev-parse", "--verify", "-q", f"{now}:./{path}", check=False).strip()
        if not current:
            return False
    with tempfile.TemporaryDirectory() as d:
        names = []
        for name, data in (("ours", ours), ("old", old), ("theirs", theirs)):
            (Path(d) / name).write_bytes(data)
            names.append(str(Path(d) / name))
        r = subprocess.run(["git", "merge-file", "-p", *names], cwd=root, capture_output=True)
    if r.returncode != 0:
        return False
    merged = subprocess.run(["git", "hash-object", "--no-filters", "--stdin"], cwd=root,
                            input=r.stdout, capture_output=True)
    return merged.returncode == 0 and merged.stdout.decode().strip() == current


def blob(root: Path, ref: str, path: str) -> str:
    """The blob id of `path` at `ref`, or "" when it does not exist there."""
    return git(root, "rev-parse", "--verify", "-q", f"{ref}:./{path}", check=False).strip()


def covers(root: Path, base: str, reviewed: str, head: str) -> list[str]:
    """Why an approval of `reviewed` does not cover `head` ([] when it does). The PR's own
    change must be the same, location-exact: the same files, and each one either identical
    or exactly `reviewed`'s version with the base branch's later change merged in cleanly
    (same_branch_change). A base merge keeps an approval; moving or editing an approved
    line, a conflict resolution, or any new change voids it (ADR-0001)."""
    if subprocess.run(["git", "cat-file", "-e", f"{reviewed}^{{commit}}"], cwd=root,
                      capture_output=True).returncode != 0:
        return [f"reviewed commit {reviewed[:12]} is not in this repository's history"]
    try:
        mb_r, mb_h = merge_base(root, base, reviewed), merge_base(root, base, head)
    except GitError as e:
        return [str(e)]
    then, now = set(committed_between(root, mb_r, reviewed)), set(committed_between(root, mb_h, head))
    out = [f"{f}: changed after the review" for f in sorted(now - then)]
    out += [f"{f}: the reviewed change to it is gone" for f in sorted(then - now)]
    for f in sorted(then & now):
        base_moved = mb_r != mb_h and blob(root, mb_r, f) != blob(root, mb_h, f)
        if not base_moved and blob(root, reviewed, f) == blob(root, head, f):
            continue
        # The base changed this file since the review: only its change merged in cleanly keeps
        # the approval (identical-to-reviewed would mean the merge undid the base's change).
        if base_moved and same_branch_change(root, base, reviewed, f, head):
            continue
        out.append(f"{f}: differs from the reviewed version beyond the base branch's change")
    return out


def _patch_id(root: Path, a: str, b: str) -> str:
    """The stable patch id of the diff from `a` to `b` ("" for an empty diff)."""
    diff = git(root, "diff", "--no-renames", a, b, check=False)
    if not diff.strip():
        return ""
    r = subprocess.run(["git", "patch-id", "--stable"], cwd=root, input=diff, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout.split(" ", 1)[0].strip()


def _undone(root: Path, reverts: dict[str, list[str]], sha: str, seen: frozenset[str] = frozenset()) -> bool:
    """`sha` is undone: some commit reverses its diff exactly (the same patch id, inverted) and
    that revert is not undone in turn. The "This reverts commit" line alone proves nothing."""
    if sha in seen:
        return False
    inverse = _patch_id(root, sha, f"{sha}^")
    return bool(inverse) and any(
        _patch_id(root, f"{r}^", r) == inverse and not _undone(root, reverts, r, seen | {sha})
        for r in reverts.get(sha, []))


def buried_trailers(root: Path, rev: str, key: str) -> list[tuple[str, list[str]]]:
    """Commits reachable from `rev` whose message has `key:` lines git does not read as trailers,
    with the values it misses: a squash merge folds each commit's trailers into the body, where
    `trailer_values` cannot see them. A commit that a later commit reverts exactly, with that
    revert still standing, is left out: the revert is how it is undone."""
    out = git(root, "log", f"--format=%H%x1f%(trailers:key={key},valueonly,separator=%x2C)%x1f%B%x1e", rev,
              check=False)
    entries, reverts = [], {}
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) != 3:
            continue
        sha, parsed, body = parts
        for target in re.findall(r"This reverts commit ([0-9a-f]{7,40})", body):
            full = git(root, "rev-parse", "--verify", "-q", f"{target}^{{commit}}", check=False).strip()
            if full:
                reverts.setdefault(full, []).append(sha)
        named = re.findall(rf"(?m)^{re.escape(key)}:[ \t]*(\S+)", body)
        seen = {v.strip() for v in parsed.split(",") if v.strip()}
        missed = sorted(set(named) - seen)
        if missed:
            entries.append((sha, missed))
    return [(sha, ids) for sha, ids in entries if not _undone(root, reverts, sha)]


def trailer_values(root: Path, rev_range: str, key: str) -> list[str]:
    """Values of a commit trailer (e.g. Sdlc-Ticket) across `rev_range`, oldest first."""
    out = git(root, "log", "--reverse", f"--format=%(trailers:key={key},valueonly,separator=%x0A)", rev_range,
              check=False)
    return [v.strip() for v in out.splitlines() if v.strip()]
