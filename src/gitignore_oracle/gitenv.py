"""Small helpers around the installed git binary."""
from __future__ import annotations

import shutil
import subprocess


def git_available() -> bool:
    return shutil.which("git") is not None


def git_version() -> str | None:
    if not git_available():
        return None
    out = subprocess.run(["git", "--version"], capture_output=True, text=True)
    return out.stdout.strip() or None
