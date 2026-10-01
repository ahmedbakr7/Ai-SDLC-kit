"""Print every API route as 'METHOD /path' for `sdlc gate` (routes.extractor = command)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.server import ROUTES  # noqa: E402

for kind, method, path, _ in ROUTES:
    if kind == "api":
        print(f"{method} {path}")
