"""A deterministic stand-in for an LLM agent, used to test `sdlc run` end to end.

Reads the generated prompt, finds play + ticket in its first line, and copies the
matching solution tree from tests/fixtures/solutions/<play>-<ticket>/ into the repo.

FAKE_AGENT_STRAY=1  first attempt also writes an out-of-scope file, so the gate fails
                    and the runner has to feed the failure back; the retry removes it.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

prompt_file = Path(sys.argv[1])
text = prompt_file.read_text(encoding="utf-8")
m = re.match(r"# sdlc play: (\w+) (T-\d+-\d+)", text)
if not m:
    sys.exit("fake agent: cannot find play/ticket in prompt")
play, tid = m.group(1).lower(), m.group(2)
repo = Path.cwd()
solution = Path(__file__).resolve().parent / "solutions" / f"{play}-{tid}"
if not solution.is_dir():
    sys.exit(f"fake agent: no solution for {play} {tid}")

retry = "The previous attempt failed the gate" in text
stray = repo / "app" / "stray_helper.py"
if os.environ.get("FAKE_AGENT_STRAY") == "1" and play == "build" and not retry:
    stray.write_text("def helper() -> None:\n    pass\n", encoding="utf-8")
elif stray.exists():
    stray.unlink()

commit = ""
ev = repo / "evidence" / f"{tid}.build.json"
if ev.is_file():
    commit = json.loads(ev.read_text(encoding="utf-8"))["commit"]

for src in solution.rglob("*"):
    if src.is_file():
        dest = repo / src.relative_to(solution)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".md":
            dest.write_text(src.read_text(encoding="utf-8").replace("{commit}", commit), encoding="utf-8")
        else:
            shutil.copyfile(src, dest)
print(f"fake agent: applied {play} {tid}" + (" (retry)" if retry else ""))
