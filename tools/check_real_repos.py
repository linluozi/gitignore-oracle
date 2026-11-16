"""Differential check on real upstream repositories with build artifacts.

Usage:
    git clone --depth=1 git@github-linluozi:psf/requests.git /tmp/gio-real/requests
    git clone --depth=1 git@github-linluozi:pallets/flask.git /tmp/gio-real/flask
    git clone --depth=1 git@github-linluozi:pytest-dev/pytest.git /tmp/gio-real/pytest
    python3 tools/check_real_repos.py --root /tmp/gio-real

The clones are read-only inputs; this script creates representative ignored
artifacts inside them (the clones are throwaway) so the .gitignore files have
real work to do, then compares every decision and its provenance with git.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gitignore_oracle.gitenv import git_version  # noqa: E402
from gitignore_oracle.gitdiff import verify_repo  # noqa: E402

# (repo dir name, upstream, representative artifacts exercised by its rules)
REPOS = [
    ("requests", "psf/requests", [
        ".coverage", "MANIFEST", "coverage.xml", "toy.py", ".cache/x",
        "cover/x", "build/x", "docs/_build/y", "requests.egg-info/PKG-INFO",
        "a.pyc", "a.swp", "env/bin/python", ".venv/x", ".pytest_cache/v",
        ".vscode/settings.json", ".workon",
    ]),
    ("flask", "pallets/flask", [
        ".idea/x", ".vscode/x", "__pycache__/m.pyc", "dist/x", ".coverage",
        "htmlcov/x", ".tox/x", "docs/_build/x", "app.py",
    ]),
    ("pytest", "pytest-dev/pytest", [
        "lib/x", "bin/x", "include/x", ".Python/x", "a.pyc", "a.pyo",
        "a.swp", "a.class", "a.orig", "x~", ".hypothesis/x",
        "src/_pytest/_version.py", ".eggs/x", "conftest.py",
    ]),
]


def head_sha(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None


def make_artifacts(repo: Path, paths: list[str]) -> None:
    for rel in paths:
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text("x", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="directory containing requests/, flask/, pytest/")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base = Path(args.root)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": git_version(),
        "note": "clones are throwaway; representative ignored artifacts are created locally",
        "repos": [],
    }
    for name, upstream, artifacts in REPOS:
        repo = base / name
        if not repo.is_dir():
            print(f"missing clone: {repo}", file=sys.stderr)
            return 2
        make_artifacts(repo, artifacts)
        res = verify_repo(repo)
        report["repos"].append({
            "dir": name,
            "upstream": upstream,
            "head": head_sha(repo),
            "paths": res["paths"],
            "files": res["files"],
            "dirs": res["dirs"],
            "git_matched": res["git_matched"],
            "git_ignored": res["git_ignored"],
            "mismatches": len(res["mismatches"]),
            "witnesses": res["mismatches"][:5],
        })
    report["total_paths"] = sum(r["paths"] for r in report["repos"])
    report["total_matched"] = sum(r["git_matched"] for r in report["repos"])
    report["total_mismatches"] = sum(r["mismatches"] for r in report["repos"])
    report["ok"] = report["total_mismatches"] == 0
    out = ROOT / "evidence" / "real_repos.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in report["repos"]:
            print(f"{r['upstream']} @ {r['head'][:12] if r['head'] else '?'}: "
                  f"{r['paths']} paths, {r['git_matched']} matched "
                  f"({r['git_ignored']} ignored), {r['mismatches']} mismatches")
        print(f"TOTAL: {report['total_paths']} paths, {report['total_matched']} matched, "
              f"{report['total_mismatches']} mismatches -> {'PASS' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())