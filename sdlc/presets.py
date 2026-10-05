"""Strictness presets (ADR-0002 step 4c): `[gate] preset` names a set of lane lists, triggers
and limits. Applied over the stack profile and under the product's own keys, which still
override it key by key, except where a preset forbids a setting: then the stricter value
holds and `doctor` reports the attempt.

- `default`: today's lists and limits.
- `hardened`: tightens existing settings, adds no new checks. No trust-based approvals; the
  mechanical lane needs a human reviewer; workflows, sdlc.toml, the kit pin and dependency
  manifests and lockfiles make a PR strict; real-stack suites are required in the standard
  and strict lanes; nothing is optional; waivers last at most 30 days and are not renewed.
- `floor`: exactly ADR-0001 section 6, for products adopting the kit: duplication and smoke
  leave every lane's lists.

`doctor` fails any resolved list below the floor whatever the preset."""
from __future__ import annotations

import copy
from typing import Any

PRESETS = ("default", "hardened", "floor")
LANE_LISTS = ("build", "test", "review", "ci", "pr", "mechanical", "strict", "spike")
FLOOR_DROPS = ("duplication", "smoke")
HARDENED_MAX_DAYS = 30
# Changes that decide what CI runs and what ships: strict, so they need a lead (ADR-0002).
HARDENED_STRICT_PATHS = [
    ".github/workflows/**", "sdlc.toml", ".sdlc", ".sdlc/**",
    "**/package.json", "**/package-lock.json", "**/npm-shrinkwrap.json", "**/pnpm-lock.yaml",
    "**/yarn.lock", "**/bun.lockb", "**/requirements*.txt", "**/pyproject.toml", "**/poetry.lock",
    "**/Pipfile", "**/Pipfile.lock", "**/uv.lock", "**/go.mod", "**/go.sum", "**/Cargo.toml",
    "**/Cargo.lock", "**/Gemfile", "**/Gemfile.lock", "**/composer.json", "**/composer.lock",
]


def name(user: dict[str, Any]) -> str:
    gate = user.get("gate", {})
    n = gate.get("preset", "default") if isinstance(gate, dict) else "default"
    if n not in PRESETS:
        raise SystemExit(f"unknown [gate] preset {n!r}; available: {', '.join(PRESETS)}")
    return n


def apply(data: dict[str, Any], preset: str) -> dict[str, Any]:
    """The preset's settings over `data` (defaults plus the stack profile)."""
    out = copy.deepcopy(data)
    g = out["gate"]
    if preset == "floor":
        for k in LANE_LISTS:
            g[k] = [n for n in g.get(k, []) if n not in FLOOR_DROPS]
    elif preset == "hardened":
        g["optional"] = []
        lanes = out.setdefault("lanes", {})
        lanes["strict_paths"] = _union(lanes.get("strict_paths", []), HARDENED_STRICT_PATHS)
        out.setdefault("waivers", {})["max_days"] = HARDENED_MAX_DAYS
    g["preset"] = preset
    return out


def enforce(data: dict[str, Any], before: dict[str, Any], user: dict[str, Any],
            preset: str) -> tuple[dict[str, Any], list[str]]:
    """After the product's keys (`data`; `before` is the preset's result under them): put back
    what the preset forbids them to loosen, and say so. The stricter value always holds, so a
    forbidden setting never weakens a gate."""
    if preset != "hardened":
        return data, []
    out, probs = copy.deepcopy(data), []
    ug, ul, uw, ua, ut = (user.get(k, {}) if isinstance(user.get(k), dict) else {}
                          for k in ("gate", "lanes", "waivers", "approval", "tests"))
    rs = ut.get("real_stack")
    if "real_stack" in ut and not (isinstance(rs, list) and {"integration", "e2e"} & set(rs)):
        probs.append(f"[tests] real_stack = {rs!r} is forbidden by the hardened preset: it must name integration "
                     "or e2e, because the standard and strict lanes prove tickets over the real stack")
        out["tests"]["real_stack"] = list(before.get("tests", {}).get("real_stack") or ["integration", "e2e"])
    if ug.get("optional"):
        probs.append(f"[gate] optional = {ug['optional']} is forbidden by the hardened preset (nothing is optional)")
        out["gate"]["optional"] = []
    if "strict_paths" in ul:
        dropped = [p for p in HARDENED_STRICT_PATHS if p not in ul["strict_paths"]]
        out["lanes"]["strict_paths"] = _union(ul["strict_paths"], HARDENED_STRICT_PATHS)
        if dropped:
            probs.append(f"[lanes] strict_paths drops {len(dropped)} path(s) the hardened preset makes strict "
                         f"(first: {dropped[0]}); they stay strict")
    n = uw.get("max_days")
    if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and 0 < n <= HARDENED_MAX_DAYS):
        probs.append(f"[waivers] max_days = {n!r} is above the hardened preset's {HARDENED_MAX_DAYS}; "
                     f"{HARDENED_MAX_DAYS} applies")
        out["waivers"]["max_days"] = HARDENED_MAX_DAYS
    if ua.get("trust_unsigned"):
        probs.append("[approval] trust_unsigned is forbidden by the hardened preset: approvals must come from "
                     "verified identities (separate accounts for agents, reviewers and leads)")
        out.setdefault("approval", {})["trust_unsigned"] = False
    return out, probs


def hardened(cfg_data: dict[str, Any]) -> bool:
    return cfg_data.get("gate", {}).get("preset") == "hardened"


def resolved(cfg_data: dict[str, Any]) -> list[str]:
    """The lists and limits a product ends up with, for `doctor` to print."""
    g = cfg_data.get("gate", {})
    out = [f"preset: {g.get('preset', 'default')}"]
    out += [f"gate.{k}: {', '.join(g.get(k, [])) or '(empty)'}" for k in (*LANE_LISTS, "optional")]
    out.append(f"lanes.strict_paths: {', '.join(cfg_data.get('lanes', {}).get('strict_paths', [])) or '(empty)'}")
    out.append(f"waivers.max_days: {cfg_data.get('waivers', {}).get('max_days')}")
    return out


def _union(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))
