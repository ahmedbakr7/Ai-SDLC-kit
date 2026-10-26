"""ADR-0009: binary files come from a declared generator or a pinned source, not from the agent.

`assets.toml` (a lead artifact) lists each binary path with its sha256 and either a `generate`
command, run from committed text sources, or a `source` URL. `sdlc assets` produces or fetches
each one and verifies its hash; the `assets` check judges every binary file a branch changes.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import re
import subprocess
import tempfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import gitutil
from .config import Config

DEFAULT_PATH = "assets.toml"
_SHA = re.compile(r"^[0-9a-f]{64}$")
SNIFF = 8000  # git's own binary heuristic: a NUL byte in the first 8000 bytes


@dataclass
class Asset:
    path: str
    sha256: str
    generate: str = ""
    source: str = ""


def rel_path(cfg: Config) -> str:
    return str(cfg.data["paths"].get("assets", DEFAULT_PATH))


def parse(text: str | None) -> tuple[list[Asset], list[str]]:
    """The declared assets and what is wrong with the file. No file declares nothing."""
    if not text:
        return [], []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return [], [f"not valid TOML: {e}"]
    rows = data.get("asset", [])
    if not isinstance(rows, list):
        return [], ["want [[asset]] tables"]
    out, probs, seen = [], [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            probs.append(f"asset {i}: want a table")
            continue
        path, sha = str(r.get("path", "")).strip(), str(r.get("sha256", "")).strip().lower()
        gen, src = str(r.get("generate", "") or "").strip(), str(r.get("source", "") or "").strip()
        where = f"asset {path or i}"
        bad = []
        segs = path.split("/")
        if not path or path.startswith("/") or "\\" in path or any(s in ("", ".", "..") for s in segs):
            bad.append("path must be a plain relative path inside the repository (no ./, //, .. or \\)")
        if not _SHA.match(sha):
            bad.append("sha256 must be 64 hex characters")
        if bool(gen) == bool(src):
            bad.append("set exactly one of generate (a command) or source (a URL)")
        if src and not src.startswith("https://"):
            bad.append("source must be an https:// URL")
        if path in seen:
            bad.append("declared twice")
        seen.add(path)
        if bad:
            probs += [f"{where}: {b}" for b in bad]
            continue
        out.append(Asset(path, sha, gen, src))
    return out, probs


def declared(cfg: Config, ref: str | None = None) -> tuple[list[Asset], list[str]]:
    """The declarations at `ref` (a commit), or in the working tree when `ref` is None."""
    rel = rel_path(cfg)
    if ref:
        return parse(gitutil.show(cfg.root, ref, "./" + rel))
    f = cfg.root / rel
    return parse(f.read_text(encoding="utf-8") if f.is_file() else None)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def binaries(root: Path, base: str) -> list[str]:
    """Binary files the branch adds or changes against merge-base(HEAD, base), deleted ones
    aside: every changed or untracked file with a NUL byte in its first 8000 bytes, plus what
    git's numstat calls binary (`-`, so a `.gitattributes` `binary` or `-diff` adds one). The
    branch's own attributes can only add binaries, never hide one: a `*.png diff` line makes git
    count a PNG's lines, but its bytes still carry the NUL."""
    mb = gitutil.merge_base(root, base)
    out = set()
    raw = gitutil.git(root, "diff", "--numstat", "-z", "--no-renames", "--relative", mb)
    for rec in raw.split("\0"):
        parts = rec.split("\t", 2)
        if len(parts) == 3 and parts[0] == "-" and parts[1] == "-" and (root / parts[2]).is_file():
            out.add(parts[2])
    for f in gitutil.changed_files(root, base):
        try:
            with open(root / f, "rb") as fh:
                if b"\0" in fh.read(SNIFF):
                    out.add(f)
        except OSError:
            continue  # deleted, or a directory (a submodule)
    return sorted(out)


def judge(cfg: Config, files: list[str], decl: list[Asset]) -> list[str]:
    """Why each binary in `files` is not covered (empty: every one is declared and matches)."""
    by_path = {a.path: a for a in decl}
    out = []
    for f in files:
        a = by_path.get(f)
        if a is None:
            out.append(f"{f}: binary, not declared in {rel_path(cfg)} (a generate command or a pinned source)")
        elif sha256(cfg.root / f) != a.sha256:
            out.append(f"{f}: sha256 differs from {rel_path(cfg)}; regenerate it with `sdlc assets`")
    return out


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """A pinned source may redirect (release downloads do), but never off https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.URLError(f"redirect to a non-https URL refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpsOnly)


def produce(cfg: Config, a: Asset, timeout: int = 600) -> str:
    """Generate or fetch one asset, then verify it. Returns a problem, or "" when it matches.
    A file that does not match is left in place for inspection, never committed by this."""
    root = cfg.root.resolve()
    dest = cfg.root / a.path
    if not dest.resolve().is_relative_to(root):
        return f"{a.path}: resolves outside the repository (a symlinked folder?)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if a.generate:
        try:
            r = subprocess.run(a.generate, shell=True, cwd=cfg.root, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return f"{a.path}: generate ran longer than {timeout}s"
        if r.returncode != 0:
            return f"{a.path}: generate exited {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}"
        if not dest.is_file():
            return f"{a.path}: generate did not write the file"
    else:
        fd, tmp = tempfile.mkstemp(dir=dest.parent)
        try:
            try:
                with _opener().open(a.source, timeout=60) as resp, os.fdopen(fd, "wb") as f:
                    fd = -1
                    for chunk in iter(lambda: resp.read(1 << 16), b""):
                        f.write(chunk)
            except (OSError, http.client.HTTPException, ValueError) as e:
                return f"{a.path}: fetching {a.source} failed: {e}"
            got = sha256(Path(tmp))
            if got != a.sha256:
                return f"{a.path}: {a.source} has sha256 {got}, not the pinned {a.sha256}"
            os.replace(tmp, dest)
        finally:
            if fd != -1:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)  # a failed or rejected download leaves nothing behind
    got = sha256(dest)
    return "" if got == a.sha256 else f"{a.path}: produced sha256 {got}, not the declared {a.sha256}"
