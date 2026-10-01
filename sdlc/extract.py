"""Extract what the code actually exposes, so it can be compared with CONTRACTS.md."""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from .artifacts import METHODS, ROUTE_LINE_RE, normalize_path
from .config import Config

ROUTE_FILE_RE = re.compile(r"^route\.(ts|tsx|js|jsx|mjs)$")
PAGE_FILE_RE = re.compile(r"^page\.(ts|tsx|js|jsx|mjs|mdx)$")
PAGE_LINE_RE = re.compile(r"^PAGE\s+(/\S*)\s*$")
EXPORT_FN_RE = re.compile(rf"export\s+(?:async\s+)?(?:function|const|let)\s+({'|'.join(METHODS)})\b")
EXPORT_LIST_RE = re.compile(r"export\s*\{([^}]*)\}")


def code_routes(cfg: Config) -> tuple[dict[str, str], list[str]]:
    """Return ({'METHOD /path': 'source file'}, errors)."""
    routes, _, errs = code_surface(cfg)
    return routes, errs


def code_surface(cfg: Config) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """({'METHOD /path': source}, {'/page/path': source}, errors). Pages come from the
    nextjs-app extractor, or from 'PAGE /path' lines printed by routes.command."""
    rc = cfg.section("routes")
    kind = rc.get("extractor", "")
    if kind == "nextjs-app":
        roots = rc.get("roots") or ["src/app", "app"]
        return _nextjs(cfg, roots), _nextjs_pages(cfg, roots), []
    if kind == "command":
        return _command(cfg, rc.get("command", ""))
    if kind == "":
        return {}, {}, ["routes.extractor is not configured"]
    return {}, {}, [f"unknown routes.extractor {kind!r}"]


def _app_path(base: Path, folder: Path) -> str | None:
    """URL path of an App Router folder, or None if it is not routable."""
    segs = []
    for seg in folder.relative_to(base).parts:
        if seg.startswith("(") and seg.endswith(")"):
            continue  # route group
        if seg.startswith("@") or seg.startswith("_"):
            return None  # parallel slot / private folder: not routable
        m = re.fullmatch(r"\[\[?(?:\.\.\.)?([^\]]+)\]?\]", seg)
        segs.append("{%s}" % m.group(1) if m else seg)
    return "/" + "/".join(segs)


def _nextjs_pages(cfg: Config, roots: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        base = cfg.root / root
        for f in sorted(base.rglob("page.*")) if base.is_dir() else []:
            if PAGE_FILE_RE.match(f.name) and "node_modules" not in f.parts:
                path = _app_path(base, f.parent)
                if path is not None:
                    out[normalize_path(path)] = cfg.rel(f)
    return out


def _nextjs(cfg: Config, roots: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        base = cfg.root / root
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("route.*")):
            if not ROUTE_FILE_RE.match(f.name) or "node_modules" in f.parts:
                continue
            path = _app_path(base, f.parent)
            if path is None:
                continue
            src = f.read_text(encoding="utf-8", errors="replace")
            methods = set(EXPORT_FN_RE.findall(src))
            for lst in EXPORT_LIST_RE.findall(src):
                for name in lst.split(","):
                    exported = name.split(" as ")[-1].strip()
                    if exported in METHODS:
                        methods.add(exported)
            for m in sorted(methods):
                out[f"{m} {normalize_path(path)}"] = cfg.rel(f)
    return out


def _command(cfg: Config, cmd: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    if not cmd:
        return {}, {}, ["routes.command is empty"]
    r = subprocess.run(cmd, shell=True, cwd=cfg.root, capture_output=True, text=True)
    if r.returncode != 0:
        return {}, {}, [f"routes.command failed ({r.returncode}): {r.stderr.strip()[:500]}"]
    out, pages, errs = {}, {}, []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if pm := PAGE_LINE_RE.match(line):
            pages[normalize_path(pm.group(1))] = "routes.command"
            continue
        m = ROUTE_LINE_RE.match(line)
        if not m:
            errs.append(f"routes.command printed a line that is neither 'METHOD /path' nor 'PAGE /path': {line}")
            continue
        out[f"{m.group(1)} {normalize_path(m.group(2))}"] = "routes.command"
    return out, pages, errs


def client_calls(cfg: Config, files: list[Path] | None = None) -> list[tuple[str, int, str]]:
    """[(file, line, path)] for API paths referenced from client code."""
    cc = cfg.section("client")
    pats = [re.compile(p) for p in cc.get("patterns", [])]
    if not pats:
        return []
    prefix = cc.get("prefix", "")
    if files is None:
        from .paths import glob_files

        files = [cfg.root / f for f in glob_files(cfg.root, cc.get("globs", []), cc.get("exclude", []))]
    out = []
    for f in sorted(set(files)):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for pat in pats:
                for m in pat.finditer(line):
                    p = m.group("path")
                    # template literals: ${x} -> {x}
                    p = re.sub(r"\$\{[^}]*\}", "{}", p)
                    if prefix and not p.startswith(prefix):
                        continue
                    out.append((cfg.rel(f), i, p))
    return out


def code_tables(cfg: Config) -> dict[str, str]:
    """{'table name': 'file:line'} for table definitions found by tables.patterns."""
    tc = cfg.section("tables")
    pats = [re.compile(p) for p in tc.get("patterns", [])]
    if not pats:
        return {}
    from .paths import glob_files

    out: dict[str, str] = {}
    for rel in glob_files(cfg.root, tc.get("globs", []), tc.get("exclude", [])):
        text = (cfg.root / rel).read_text(encoding="utf-8", errors="replace")
        for pat in pats:
            for m in pat.finditer(text):
                out.setdefault(m.group("name"), f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
    return out


def path_matches(path: str, contract_paths: set[str]) -> bool:
    """Does a concrete or templated client path match any contract route path?"""
    norm = normalize_path(path)
    if norm in contract_paths:
        return True
    segs = norm.strip("/").split("/")
    for cp in contract_paths:
        csegs = cp.strip("/").split("/")
        if len(csegs) != len(segs):
            continue
        if all(c == s or c == "{}" or s == "{}" for c, s in zip(csegs, segs)):
            return True
    return False


def split_cmd(cmd: str) -> list[str]:
    return shlex.split(cmd)
