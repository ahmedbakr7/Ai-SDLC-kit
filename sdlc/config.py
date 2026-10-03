"""Product configuration: sdlc.toml at the product root, layered over a stack profile."""
from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info < (3, 11):  # pragma: no cover
    sys.exit("sdlc needs Python >= 3.11 (tomllib)")
import tomllib

KIT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_NAME = "sdlc.toml"

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "profile": "",
    "paths": {
        "intent": "intent",
        "design": "design",
        "arch": "arch",
        "contracts": "arch/CONTRACTS.md",
        "decisions": "decisions",
        "tickets": "tickets",
        "reviews": "reviews",
        "evidence": "evidence",
        "ops": "ops",
        "skills": "skills",
        "skills_lock": "skills.lock.json",
        "baseline": "sdlc-baseline.json",   # known failures a red base branch started with
    },
    # Shell commands. Placeholders: {junit} (JUnit XML output path), {port}, {base_url}.
    "commands": {},
    "gate": {
        # Checks every play's gate runs, in order. A missing command for a
        # required check is a FAILURE, never a silent pass.
        "build": ["artifacts", "scope", "immutable", "contracts", "lint", "typecheck", "unit", "ac-coverage", "ac-red",
                  "test-quality", "duplication", "build", "smoke", "skills"],
        "test": ["artifacts", "scope", "immutable", "contracts", "lint", "typecheck", "unit", "integration",
                 "e2e", "ac-coverage", "test-quality", "build", "smoke", "skills"],
        "review": ["artifacts", "scope", "immutable", "review-file"],
        "ci": ["artifacts", "immutable", "contracts", "lint", "typecheck", "unit", "integration", "e2e",
               "ac-coverage", "test-quality", "duplication", "build", "smoke", "skills"],
        # One ticket's whole branch, as CI sees it: every file is in some play's write set,
        # status moved only legally, and a `done` ticket carries an approval of what ships.
        "pr": ["artifacts", "scope", "immutable", "review-file"],
        # Checks that may be skipped when their command is not configured.
        "optional": ["integration", "e2e", "duplication"],
        "max_attempts": 3,
    },
    "app": {
        "port": 3123,
        "host": "127.0.0.1",
        "ready_path": "/",
        "ready_timeout": 120,
        # A route "exists" when the server does not answer with the framework's
        # not-found page. Status codes that always mean "route missing":
        "missing_status": [405],
        # 404 counts as missing only when the body is not this content type
        # (an app-level JSON 404 is a real handler answering).
        "app_404_content_type": "application/json",
        # How POST/PUT/PATCH/DELETE routes are probed: "request" sends the method (POST/PUT/
        # PATCH with body {}), which may write data; "options" sends OPTIONS and requires the
        # method in the Allow header (Next.js route handlers answer OPTIONS this way).
        "mutating_probe": "request",
    },
    "routes": {
        "extractor": "",       # nextjs-app | command
        "command": "",         # prints "METHOD /path" and optional "PAGE /path" lines (extractor=command)
        "roots": [],           # extractor-specific source roots
    },
    "client": {
        # Regexes with a named group 'path' that find API calls in client code.
        "patterns": [],
        "globs": [],
        "exclude": [],
        "prefix": "",          # only paths starting with this are checked
    },
    "tables": {
        # Regexes with a named group 'name', searched across whole files (definitions often
        # span lines), that find table definitions; each must be a CONTRACTS ```tables entry.
        "patterns": [],
        "globs": [],
        "exclude": [],
    },
    "tests": {
        "globs": [],                       # files that count as tests (for scope + quality)
        "unit_beside": True,               # build may add tests beside listed files
        "integration_globs": [],           # test play write set
        # Suites whose tagged tests prove a ticket through the real stack (the test play).
        # [] = the lead accepts unit-only proof; doctor fails if none of these is configured.
        "real_stack": ["integration", "e2e"],
        "forbid": [],                      # [{regex, message}] patterns banned in tests
    },
    "scope": {
        "always_allowed": [],              # globs any play may touch (lockfiles, snapshots)
        # Globs a PR that moves no ticket may change, besides the lead artifacts, sdlc.toml,
        # AGENTS.md and generated adapter files (`gate pr` without a ticket).
        "lead_allowed": [],
        # What a PR that moves no ticket may do with other files (code): "warn" reports them
        # and passes (human hotfixes), "fail" requires a ticket for every code change.
        "lead_code": "warn",
    },
    "vcs": {
        "base": "main",
        "branch": "{play}/{id}",
        "pr_command": "",                  # e.g. gh pr create --fill --base {base}
    },
    "review": {
        "require_distinct_agent": True,
    },
    "adapters": {
        "tools": ["claude", "cursor", "copilot", "gemini"],
    },
    "agents": {},
}


@dataclass
class Config:
    root: Path
    data: dict[str, Any]
    source: Path | None = None
    profile_name: str = ""
    warnings: list[str] = field(default_factory=list)

    def path(self, key: str) -> Path:
        return self.root / self.data["paths"][key]

    def rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()

    @property
    def commands(self) -> dict[str, str]:
        return self.data["commands"]

    def section(self, name: str) -> dict[str, Any]:
        return self.data.get(name, {})


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def find_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / CONFIG_NAME).is_file():
            return p
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p
    return cur


def load_profile(name: str) -> dict[str, Any]:
    f = KIT_ROOT / "profiles" / f"{name}.toml"
    if not f.is_file():
        avail = ", ".join(sorted(p.stem for p in (KIT_ROOT / "profiles").glob("*.toml")))
        raise SystemExit(f"unknown profile {name!r}; available: {avail}")
    try:
        return tomllib.loads(f.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{f}: {e}") from None


def load(root: Path | None = None, text: str | None = None) -> Config:
    """Load sdlc.toml from `root`, or from `text` (e.g. the base branch's committed version)."""
    root = find_root(root)
    src = root / CONFIG_NAME
    user: dict[str, Any] = {}
    if text is not None or src.is_file():
        try:
            user = tomllib.loads(text if text is not None else src.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"{src}: {e}") from None
    data = copy.deepcopy(DEFAULTS)
    profile = user.get("profile", "")
    if profile:
        data = deep_merge(data, load_profile(profile))
    data = deep_merge(data, user)
    cfg = Config(root=root, data=data, source=src if src.is_file() else None, profile_name=profile)
    unknown = set(user) - set(DEFAULTS)
    if unknown:
        cfg.warnings.append(f"{CONFIG_NAME}: unknown top-level keys: {', '.join(sorted(unknown))}")
    return cfg
