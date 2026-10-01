"""Vendored third-party skills, pinned by commit and content hash."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import fm
from .config import KIT_ROOT, Config

CATALOG = KIT_ROOT / "skills" / "vendor" / "catalog.json"


def tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        rel = f.relative_to(d).as_posix()
        data = f.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def lock_path(cfg: Config) -> Path:
    return cfg.root / cfg.data["paths"]["skills_lock"]


def read_lock(cfg: Config) -> dict:
    p = lock_path(cfg)
    if not p.is_file():
        return {"version": 1, "skills": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def write_lock(cfg: Config, lock: dict) -> None:
    lock["skills"] = dict(sorted(lock["skills"].items()))
    lock_path(cfg).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def vendor_dir(cfg: Config) -> Path:
    return cfg.path("skills") / "vendor"


def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else {"skills": {}}


def add(cfg: Config, spec: str, name: str | None = None, ref: str | None = None,
        path: str | None = None) -> dict:
    """spec is a catalog key (e.g. superpowers/test-driven-development) or a git URL."""
    cat = catalog()["skills"]
    if spec in cat:
        entry = cat[spec]
        source, path = entry["source"], path or entry["path"]
        ref = ref or entry.get("ref", "main")
        name = name or spec.split("/")[-1]
    else:
        if not path:
            raise SystemExit("a git URL needs --path <dir inside the repo containing SKILL.md>")
        source, ref = spec, ref or "main"
        name = name or Path(path).name
    with tempfile.TemporaryDirectory() as tmp:
        run = lambda *a: subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True, text=True)
        run("init", "-q")
        run("remote", "add", "origin", source)
        try:
            run("fetch", "-q", "--depth", "1", "origin", ref)
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"cannot fetch {ref} from {source}: {e.stderr.strip()}") from None
        run("checkout", "-q", "FETCH_HEAD")
        sha = run("rev-parse", "HEAD").stdout.strip()
        src = Path(tmp) / path
        if not (src / "SKILL.md").is_file():
            raise SystemExit(f"{source}@{sha[:10]}:{path} has no SKILL.md")
        dest = vendor_dir(cfg) / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
    lock = read_lock(cfg)
    lock["skills"][name] = {"source": source, "ref": sha, "path": path, "sha256": tree_hash(dest)}
    write_lock(cfg, lock)
    return lock["skills"][name]


def verify(cfg: Config) -> list[str]:
    lock = read_lock(cfg)["skills"]
    vd = vendor_dir(cfg)
    problems = []
    for name, e in lock.items():
        d = vd / name
        if not (d / "SKILL.md").is_file():
            problems.append(f"locked skill {name} missing at {cfg.rel(d)}")
            continue
        if tree_hash(d) != e.get("sha256"):
            problems.append(f"skill {name} was edited after pinning (hash mismatch); re-run `sdlc skills add`")
        try:
            data, _ = fm.load(d / "SKILL.md")
        except fm.ParseError:
            data = _loose_name(d / "SKILL.md")
        if not data.get("name") or not data.get("description"):
            problems.append(f"skill {name}: SKILL.md needs name and description")
    if vd.is_dir():
        for d in sorted(p for p in vd.iterdir() if p.is_dir()):
            if d.name not in lock:
                problems.append(f"{cfg.rel(d)} is not in {cfg.data['paths']['skills_lock']}; add it with `sdlc skills add`")
    return problems


def _loose_name(p: Path) -> dict:
    """Third-party SKILL.md frontmatter may use YAML beyond our subset; read name/description only."""
    out = {}
    head, _, _ = fm.split(p.read_text(encoding="utf-8"))
    for line in (head or "").split("\n"):
        for k in ("name", "description"):
            if line.startswith(k + ":"):
                out[k] = line.split(":", 1)[1].strip()
    return out


def resolve(cfg: Config, name: str) -> Path | None:
    """Locate a skill named on a ticket: kit play skill, product skill, or vendor skill."""
    for base in (KIT_ROOT / "skills", cfg.path("skills"), vendor_dir(cfg)):
        p = base / name / "SKILL.md"
        if p.is_file():
            return p
    if name.startswith("vendor/"):
        p = vendor_dir(cfg) / name[len("vendor/"):] / "SKILL.md"
        if p.is_file():
            return p
    return None
