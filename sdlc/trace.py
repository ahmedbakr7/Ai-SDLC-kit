"""`sdlc trace`: requirement -> ticket -> acceptance criterion -> passing test."""
from __future__ import annotations

import json

from .artifacts import Repo


def matrix(repo: Repo) -> dict:
    reqs = repo.requirements()
    by_req: dict[str, list[str]] = {r: [] for r in reqs}
    for t in repo.tickets.values():
        for r in t.requirements:
            by_req.setdefault(r, []).append(t.id)
    tickets = {}
    for tid, t in sorted(repo.tickets.items()):
        ev_path = repo.cfg.path("evidence") / f"{tid}.build.json"
        ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else {}
        acs = {}
        for ac, text in t.acs:
            tag = f"{tid}/{ac}"
            acs[ac] = {"text": text, "proof": ev.get("ac", {}).get(tag, {}).get("status", "none")}
        tickets[tid] = {"status": t.status, "requirements": t.requirements, "acs": acs,
                        "evidence": ev.get("result", "none")}
    accepted = {r.id for s in repo.specs if s.status == "accepted" for r in s.requirements}
    return {
        "requirements": {r: {"tickets": sorted(ts), "accepted": r in accepted,
                             "text": reqs[r].text if r in reqs else ""}
                         for r, ts in sorted(by_req.items())},
        "tickets": tickets,
    }


def problems(m: dict) -> list[str]:
    out = []
    for r, v in m["requirements"].items():
        if v["accepted"] and not v["tickets"]:
            out.append(f"{r}: accepted requirement has no ticket")
    for tid, t in m["tickets"].items():
        if t["status"] in ("in_review", "done"):
            if t["evidence"] != "pass":
                out.append(f"{tid}: {t['status']} without passing build evidence")
            for ac, a in t["acs"].items():
                if a["proof"] != "passed":
                    out.append(f"{tid}/{ac}: {t['status']} but proof is {a['proof']}")
    return out


def render(m: dict) -> str:
    lines = ["| Requirement | Tickets | AC proven |", "|---|---|---|"]
    for r, v in m["requirements"].items():
        ts = v["tickets"]
        proven = sum(1 for t in ts for a in m["tickets"][t]["acs"].values() if a["proof"] == "passed")
        total = sum(len(m["tickets"][t]["acs"]) for t in ts)
        lines.append(f"| {r} | {', '.join(ts) or '—'} | {proven}/{total} |")
    return "\n".join(lines)
