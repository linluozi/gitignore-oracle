from pathlib import Path

from gitignore_oracle.engine import GitIgnore


def make(tmp_path: Path, files: dict[str, str], dirs=()):
    for d in dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_last_matching_line_wins(tmp_path):
    make(tmp_path, {
        ".gitignore": "*.log\n!keep.log\n",
        "a.log": "", "keep.log": "",
    })
    gi = GitIgnore(tmp_path)
    assert gi.check("a.log").ignored
    assert not gi.check("keep.log").ignored
    assert gi.check("keep.log").line == 2


def test_deepest_gitignore_wins(tmp_path):
    make(tmp_path, {
        ".gitignore": "*.log\n",
        "sub/.gitignore": "!keep.log\n",
        "sub/a.log": "", "sub/keep.log": "",
    })
    gi = GitIgnore(tmp_path)
    assert gi.check("sub/a.log").ignored
    d = gi.check("sub/keep.log")
    assert not d.ignored
    assert d.source == "sub/.gitignore" and d.line == 1


def test_parent_exclusion_blocks_reinclude(tmp_path):
    make(tmp_path, {
        ".gitignore": "build/\n!build/keep.txt\n",
        "build/keep.txt": "",
    })
    gi = GitIgnore(tmp_path)
    d = gi.check("build/keep.txt")
    assert d.ignored
    assert d.via == "build"
    assert d.pattern == "build/"


def test_reinclude_allowed_when_parent_not_ignored(tmp_path):
    make(tmp_path, {
        ".gitignore": "build/*\n!build/keep.txt\n",
        "build/keep.txt": "", "build/x.txt": "",
    })
    gi = GitIgnore(tmp_path)
    assert not gi.check("build/keep.txt").ignored
    assert gi.check("build/x.txt").ignored


def test_dir_only_rule_does_not_match_file(tmp_path):
    make(tmp_path, {
        ".gitignore": "cache/\n",
        "cache": "",  # a regular file with the same name
    })
    gi = GitIgnore(tmp_path)
    assert not gi.check("cache", is_dir=False).ignored


def test_unmatched_path(tmp_path):
    make(tmp_path, {".gitignore": "*.log\n", "a.txt": ""})
    d = GitIgnore(tmp_path).check("a.txt")
    assert not d.matched and not d.ignored
    assert d.reason == "no rule matched"


def test_anchored_root_rule(tmp_path):
    make(tmp_path, {
        ".gitignore": "/root.txt\n",
        "root.txt": "", "sub/root.txt": "",
    })
    gi = GitIgnore(tmp_path)
    assert gi.check("root.txt").ignored
    assert not gi.check("sub/root.txt").ignored


def test_info_exclude_lowest_precedence(tmp_path):
    make(tmp_path, {
        ".gitignore": "!keep.log\n",
        ".git/info/exclude": "*.log\n",
        "keep.log": "", "other.log": "",
    })
    gi = GitIgnore(tmp_path)
    assert not gi.check("keep.log").ignored
    assert gi.check("other.log").ignored
    assert gi.check("other.log").source == ".git/info/exclude"


def test_audit_detects_cross_file_override(tmp_path):
    make(tmp_path, {
        ".gitignore": "!sub/x.txt\n",
        "sub/.gitignore": "x.txt\n",
        "sub/x.txt": "",
    })
    report = GitIgnore(tmp_path).audit()
    kinds = {(f["kind"], f["witness"]) for f in report["findings"]}
    assert ("dead_by_other_ignore", "sub/x.txt") in kinds


def test_audit_finds_dead_negations(tmp_path):
    make(tmp_path, {
        ".gitignore": "*.log\n!keep.log\nbuild/\n!build/keep.txt\ndocs/\n!docs/ok.md\n",
        "keep.log": "", "build/keep.txt": "", "docs/ok.md": "",
    })
    report = GitIgnore(tmp_path).audit()
    kinds = {(f["kind"], f["witness"]) for f in report["findings"]}
    assert ("dead_by_parent", "build/keep.txt") in kinds
    assert ("dead_by_parent", "docs/ok.md") in kinds
    # the reachable negation must not be reported
    assert all("keep.log" != f["witness"] for f in report["findings"])
