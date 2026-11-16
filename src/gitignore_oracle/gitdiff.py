"""Differential verification against the real `git check-ignore`.

This module is both a library helper (`python -m gitignore_oracle verify`) and
the machinery used to produce `evidence/differential.json`.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .engine import GitIgnore

GIT_ENV_ARGS = ["-c", "core.excludesFile=/dev/null"]


def enumerate_paths(root: str | Path) -> list[tuple[str, bool]]:
    """All files and directories in the work tree, as (posix relpath, is_dir)."""
    root = Path(root)
    out: list[tuple[str, bool]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        base = Path(dirpath).relative_to(root).as_posix()
        base = "" if base == "." else base
        for d in dirnames:
            out.append(((base + "/" + d) if base else d, True))
        for f in sorted(filenames):
            out.append(((base + "/" + f) if base else f, False))
    return out


def git_decisions(
    root: str | Path, paths: list[tuple[str, bool]]
) -> dict[str, tuple[str, int, str] | None]:
    """Ask git for the deciding rule of every path (None = no rule matched)."""
    if not paths:
        return {}
    payload = b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p, _ in paths)
    proc = subprocess.run(
        ["git", "-C", str(root), *GIT_ENV_ARGS, "check-ignore",
         "--no-index", "-v", "-z", "--stdin"],
        input=payload, capture_output=True,
    )
    # git exits 1 when no path is ignored, 0 otherwise; 128+ is a real error.
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"git check-ignore failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')}"
        )
    fields = proc.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    out: dict[str, tuple[str, int, str] | None] = {p: None for p, _ in paths}
    if len(fields) % 4 != 0:
        raise RuntimeError(f"unexpected -z field count: {len(fields)}")
    for i in range(0, len(fields), 4):
        source = fields[i].decode("utf-8", "surrogateescape")
        line = int(fields[i + 1])
        pattern = fields[i + 2].decode("utf-8", "surrogateescape")
        pathname = fields[i + 3].decode("utf-8", "surrogateescape")
        out[pathname] = (source, line, pattern)
    return out


def verify_repo(root: str | Path) -> dict:
    root = Path(root)
    paths = enumerate_paths(root)
    gi = GitIgnore(root)
    got = git_decisions(root, paths)
    mismatches: list[dict] = []
    matched = 0
    ignored = 0
    for rel, is_dir in paths:
        dec = gi.check(rel, is_dir=is_dir)
        want = got.get(rel)
        if want is not None:
            matched += 1
            # git prints negation rules too; the path is then NOT ignored.
            if not want[2].startswith("!"):
                ignored += 1
        if dec.matched != (want is not None):
            mismatches.append({
                "path": rel, "kind": "matched", "engine": dec.to_dict(),
                "git": want,
            })
            continue
        if want is None:
            continue
        source, line, pattern = want
        if (dec.source, dec.line, dec.pattern) != (source, line, pattern):
            mismatches.append({
                "path": rel, "kind": "provenance", "engine": dec.to_dict(),
                "git": {"source": source, "line": line, "pattern": pattern},
            })
    return {
        "root": str(root),
        "paths": len(paths),
        "dirs": sum(1 for _, d in paths if d),
        "files": sum(1 for _, d in paths if not d),
        "git_matched": matched,
        "git_ignored": ignored,
        "mismatches": mismatches,
        "ok": not mismatches,
    }
