"""Build the differential evidence file used by the README.

Run:  python3 tools/run_evidence.py

It generates 16 real git repositories in a temporary directory, compares the
oracle's decision (including source file / line / pattern) against
`git check-ignore -v -z --no-index` for every file and directory, verifies
every reported dead negation with git, and measures decision throughput.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gen_corpus import build_all  # noqa: E402
from gitignore_oracle import GitIgnore  # noqa: E402
from gitignore_oracle.gitenv import git_version  # noqa: E402
from gitignore_oracle.gitdiff import (  # noqa: E402
    enumerate_paths, git_decisions, verify_repo,
)

REPO_COUNT = 16


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "surrogateescape")).hexdigest()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="gio-evidence-")
    started = datetime.now(timezone.utc).isoformat()
    try:
        repos = build_all(tmp, REPO_COUNT)
        per_repo = []
        unique_paths: set[str] = set()
        total_mismatches = 0
        dead_records = []
        unconfirmed = 0
        for r in repos:
            rep = verify_repo(r["root"])
            audit = GitIgnore(r["root"]).audit()
            for path, _ in enumerate_paths(r["root"]):
                unique_paths.add(sha256(f"{r['seed']}\0{path}"))
            total_mismatches += len(rep["mismatches"])
            per_repo.append({
                "seed": r["seed"],
                "paths": rep["paths"],
                "files": rep["files"],
                "dirs": rep["dirs"],
                "git_matched": rep["git_matched"],
                "git_ignored": rep["git_ignored"],
                "mismatches": len(rep["mismatches"]),
                "rule_files": len(audit["files"]),
                "rules": audit["total_rules"],
                "negations": audit["negations"],
                "dead_rules": len(audit["findings"]),
            })
            for f in audit["findings"]:
                got = git_decisions(r["root"], [(f["witness"], False)]).get(f["witness"])
                d = f["decided_by"]
                ok = (
                    got is not None
                    and not got[2].startswith("!")
                    and got == (d["source"], d["line"], d["pattern"])
                )
                if not ok:
                    unconfirmed += 1
                dead_records.append({
                    "repo_seed": r["seed"],
                    "kind": f["kind"],
                    "rule": f["rule"],
                    "witness": f["witness"],
                    "git_decided_by": (
                        {"source": got[0], "line": got[1], "pattern": got[2]}
                        if got else None
                    ),
                    "confirmed_by_git": ok,
                })

        # Throughput: decisions/sec over every path, three passes.
        samples = []
        for _ in range(3):
            n = 0
            t0 = time.perf_counter()
            for r in repos:
                gi = GitIgnore(r["root"])
                for path, is_dir in enumerate_paths(r["root"]):
                    gi.check(path, is_dir=is_dir)
                    n += 1
            elapsed = time.perf_counter() - t0
            samples.append(n / elapsed if elapsed else 0.0)
        throughput = {
            "passes": 3,
            "decisions_per_sec_median": round(statistics.median(samples), 1),
            "decisions_per_sec_samples": [round(s, 1) for s in samples],
        }

        # One explicit counterexample: git refuses the re-inclusion.
        demo = dead_records[0] if dead_records else None
        report = {
            "generated_at": started,
            "python": platform.python_version(),
            "git": git_version(),
            "kernel": platform.platform(),
            "repos": REPO_COUNT,
            "unique_paths_sha256": len(unique_paths),
            "unique_paths_definition": "sha256(seed + NUL + repo_relative_path), one per (repo, path)",
            "total_paths_checked": sum(x["paths"] for x in per_repo),
            "total_files": sum(x["files"] for x in per_repo),
            "total_dirs": sum(x["dirs"] for x in per_repo),
            "git_matched": sum(x["git_matched"] for x in per_repo),
            "git_ignored": sum(x["git_ignored"] for x in per_repo),
            "mismatches": total_mismatches,
            "per_repo": per_repo,
            "dead_rules": {
                "found": len(dead_records),
                "by_kind": {
                    k: sum(1 for d in dead_records if d["kind"] == k)
                    for k in sorted({d["kind"] for d in dead_records})
                },
                "confirmed_by_git": len(dead_records) - unconfirmed,
                "unconfirmed": unconfirmed,
                "examples": dead_records[:6],
            },
            "throughput": throughput,
            "counterexample": demo,
            "ok": total_mismatches == 0 and unconfirmed == 0,
        }
        out = ROOT / "evidence" / "differential.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "repos": report["repos"],
            "unique_paths_sha256": report["unique_paths_sha256"],
            "total_paths_checked": report["total_paths_checked"],
            "git_matched": report["git_matched"],
            "git_ignored": report["git_ignored"],
            "mismatches": report["mismatches"],
            "dead_rules": report["dead_rules"]["found"],
            "dead_unconfirmed": report["dead_rules"]["unconfirmed"],
            "throughput": throughput["decisions_per_sec_median"],
            "ok": report["ok"],
        }, indent=2))
        return 0 if report["ok"] else 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
