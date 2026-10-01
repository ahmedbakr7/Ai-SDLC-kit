"""Shared fixtures: a throwaway git repo holding a copy of the example product."""
from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
EXAMPLE = KIT / "examples" / "returns-app"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(KIT))
from sdlc import cli  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


class ProductRepo:
    def __init__(self, name: str = "product") -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / name
        shutil.copytree(EXAMPLE, self.root, ignore=shutil.ignore_patterns(".sdlc-run", "__pycache__"))
        agent = f'"{Path(sys.executable).as_posix()}" "{(FIXTURES / "fake_agent.py").as_posix()}" {{prompt_file}}'
        with open(self.root / "sdlc.toml", "a", encoding="utf-8") as f:
            f.write(f"\n[agents.fake]\ncommand = '''{agent}'''\n"
                    f"\n[agents.fake-reviewer]\ncommand = '''{agent}'''\n")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "kit@example.com")
        git(self.root, "config", "user.name", "kit tests")
        git(self.root, "config", "core.autocrlf", "false")
        self.commit("example product")

    def commit(self, msg: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", msg)

    def sdlc(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(["--root", str(self.root), *args])
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if not isinstance(e.code, int) and e.code:
                    print(e.code)
        return code, out.getvalue()

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def close(self) -> None:
        try:
            self.tmp.cleanup()
        except OSError:
            pass  # Windows may hold a handle on a just-killed server's files
