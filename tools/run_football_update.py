"""Stable root entrypoint required by the football update Skill."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"D:\codex")
PROJECTS = ROOT / "技能项目"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROJECTS) not in sys.path:
    sys.path.insert(0, str(PROJECTS))

from football_update.run_football_update import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    raise SystemExit(main())
