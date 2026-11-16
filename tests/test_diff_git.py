import subprocess

import pytest

from gitignore_oracle.gitenv import git_available
from gitignore_oracle.gitdiff import verify_repo


def _repo(tmp_path):
    (tmp_path / ".gitignore").write_text(
        "*.log\n!keep.log\nbuild/\n!build/keep.txt\n/docs/tmp\n**/cache\n"
        "foo/**/bar\nx/**\n[ab]*.tmp\n\\#literal\n",
        encoding="utf-8",
    )
    for rel in [
        "a.log", "keep.log", "build/keep.txt", "docs/tmp/x.md",
        "cache/x", "z/cache/y", "foo/x/y/bar", "x/y", "a.tmp", "b.tmp",
        "c.tmp", "#literal", "plain.txt", "sub/keep.log",
    ]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "tmp").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.mark.skipif(not git_available(), reason="git not installed")
def test_differential_against_git(tmp_path):
    root = _repo(tmp_path)
    report = verify_repo(root)
    assert report["paths"] > 15
    assert report["git_ignored"] > 5
    assert report["mismatches"] == []
    assert report["ok"]


@pytest.mark.skipif(not git_available(), reason="git not installed")
def test_dead_rule_witness_is_confirmed_by_git(tmp_path):
    root = _repo(tmp_path)
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", "core.excludesFile=/dev/null",
         "check-ignore", "--no-index", "-v", "build/keep.txt"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert ".gitignore:3:build/" in proc.stdout
    assert proc.stdout.strip().endswith("build/keep.txt")


def test_verify_repo_rejects_non_repository(tmp_path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_repo(tmp_path)


def test_verify_repo_empty_tree(tmp_path):
    report = verify_repo(tmp_path)
    assert report["paths"] == 0 and report["ok"]
