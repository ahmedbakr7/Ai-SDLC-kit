"""Thin git helpers (subprocess, no libraries)."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD", check=False).strip() or "(no commits)"


def is_dirty(root: Path) -> bool:
    return bool(git(root, "status", "--porcelain", check=False).strip())


def merge_base(root: Path, base: str) -> str:
    for ref in (base, f"origin/{base}"):
        out = git(root, "merge-base", "HEAD", ref, check=False).strip()
        if out:
            return out
    raise GitError(f"cannot find merge base with {base!r} (fetch it, or pass --base)")


def changed_files(root: Path, base: str) -> list[str]:
    """Files changed vs merge-base(HEAD, base), including staged, unstaged and untracked."""
    mb = merge_base(root, base)
    # --relative / ls-files: paths relative to the product root, so a product nested
    # in a monorepo only sees (and is only judged on) its own files.
    names = set(git(root, "diff", "--name-only", "--no-renames", "--relative", mb).split("\n"))
    names |= set(git(root, "ls-files", "--others", "--exclude-standard").split("\n"))
    return sorted(n.strip() for n in names if n.strip())


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=root,
                          capture_output=True).returncode == 0


def show(root: Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def changed_since(root: Path, ref: str) -> list[str]:
    """Files changed after commit `ref` (committed or not)."""
    names = set(git(root, "diff", "--name-only", "--no-renames", "--relative", ref).splitlines())
    names |= set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(n.strip() for n in names if n.strip())
