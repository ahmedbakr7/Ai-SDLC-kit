"""Regenerate the example's committed proof for T-042-01 by running the real conveyor.

Starts from the example *before* T-042-01 was built, then runs build -> test -> review
with the fake agent and copies the resulting evidence and review back into
examples/returns-app. Run after changing the gate or the example:

    python tests/regen_example.py
"""
import shutil
import sys

from helpers import EXAMPLE, ProductRepo


def main(write: bool = True) -> int:
    p = ProductRepo()
    try:
        for rel in ("app/returns.py", "app/server.py", "app/test_returns.py", "tests/test_http_returns.py",
                    "evidence/T-042-01.build.json", "evidence/T-042-01.test.json", "reviews/T-042-01.md"):
            (p.root / rel).unlink(missing_ok=True)
        p.write("app/server.py", '"""HTTP entry point (built by T-042-01)."""\n')
        for rel, frm, to in (("tickets/T-042-01-returns-api.md", "status: done", "status: ready"),
                             ("tickets/T-042-02-order-page.md", "status: ready", "status: draft")):
            p.write(rel, p.read(rel).replace(frm, to))
        p.commit("example before T-042-01")

        steps = [("run", "build", "T-042-01", "--agent", "fake"),
                 ("run", "test", "T-042-01", "--agent", "fake"),
                 ("run", "review", "T-042-01", "--agent", "fake-reviewer"),
                 ("status", "T-042-01", "done", "--as", "merge")]
        for args in steps:
            code, out = p.sdlc(*args)
            print(out)
            if code != 0:
                print(f"FAILED: sdlc {' '.join(args)}", file=sys.stderr)
                return 1
        for rel in ("evidence/T-042-01.build.json", "evidence/T-042-01.test.json", "reviews/T-042-01.md"):
            if not write:
                continue
            (EXAMPLE / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p.root / rel, EXAMPLE / rel)
            print(f"wrote examples/returns-app/{rel}")
        return 0
    finally:
        p.close()


if __name__ == "__main__":
    sys.exit(main())
