"""Generate deterministic, real git repositories used as the differential corpus.

Every repository is a real work tree initialised with `git init`; every path is
a real file or directory. Nothing is mocked: the oracle is the installed git.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

BASES = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
    "theta", "iota", "kappa", "lambda", "mu", "nu", "xi",
]
EXTS = ["log", "py", "txt", "tmp", "pyc"]
DIRS = [
    "build", "build/sub", "cache", "docs", "docs/tmp", "src", "src/deep",
    "vendor", "sub/deep", "foo/x/y", "z/deep", "empty",
]

ROOT_RULES = [
    "*.log", "!important.log", "!keep.log",
    "build/", "!build/keep.txt",
    "/root.txt", "**/cache", "docs/**/tmp",
    "*.tmp", "!notes.tmp",
    "vendor/**", "!vendor/needed.py",
    "sub/deep/", "!sub/deep/ok.txt",
    "foo/**/bar", "**/deep",
    "[ab]*.tmp", "!b.tmp",
    "\\#literal", "\\!bang", "trailing\\ ",
    "**/*.bak", "src/*.pyc", "!src/keep.pyc",
    "empty/", "scratch?", "x/**",
]

NESTED_RULES = {
    "src": ["!beta.py", "*.tmp", "deep/", "!deep/ok.txt"],
    "docs": ["tmp/", "!tmp/keep.md", "*.md", "!README.md"],
    "sub": ["deep/", "!deep/ok.txt"],
    "foo": ["x/", "!x/y/bar"],
}


def _touch(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_files(root: Path) -> None:
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    for b in BASES:
        for ext in EXTS:
            _touch(root / f"{b}.{ext}")
    for sub in ("build", "build/sub", "cache", "docs", "src/deep", "vendor", "foo/x/y"):
        for b in BASES[:5]:
            _touch(root / sub / f"{b}.txt")
    for b in BASES:
        _touch(root / "src" / f"{b}.py")
        _touch(root / "src" / f"{b}.pyc")
    _touch(root / "docs" / "README.md")
    _touch(root / "docs" / "tmp" / "keep.md")
    _touch(root / "sub" / "deep" / "ok.txt")
    _touch(root / "src" / "deep" / "ok.txt")
    _touch(root / "src" / "keep.pyc")
    _touch(root / "vendor" / "needed.py")
    _touch(root / "build" / "keep.txt")
    _touch(root / "foo" / "x" / "y" / "bar")
    _touch(root / "z" / "deep" / "f")
    _touch(root / "deep" / "f")
    _touch(root / "a.tmp")
    _touch(root / "b.tmp")
    _touch(root / "ab1.tmp")
    _touch(root / "root.txt")
    _touch(root / "notes.tmp")
    _touch(root / "#literal")
    _touch(root / "!bang")
    _touch(root / "trailing ")
    _touch(root / "keep.log")
    _touch(root / "important.log")
    _touch(root / "README.md")
    _touch(root / "r1.bak")
    _touch(root / "src" / "r2.bak")


def generate(dest: str | Path, seed: int) -> Path:
    root = Path(dest)
    root.mkdir(parents=True)
    rng = random.Random(seed)
    _make_files(root)
    picked = rng.sample(ROOT_RULES, rng.randint(9, 14))
    # Always keep at least one negative rule whose witness exists so the
    # dead-rule audit has something real to find.
    for must in ("build/", "!build/keep.txt"):
        if must not in picked:
            picked.append(must)
    (root / ".gitignore").write_text("\n".join(picked) + "\n", encoding="utf-8")
    for d in rng.sample(sorted(NESTED_RULES), rng.randint(1, 3)):
        lines = rng.sample(NESTED_RULES[d], rng.randint(1, len(NESTED_RULES[d])))
        (root / d / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def build_all(dest_root: str | Path, count: int = 12) -> list[dict]:
    out = []
    for seed in range(count):
        root = generate(Path(dest_root) / f"repo-{seed:02d}", seed)
        out.append({"seed": seed, "root": str(root)})
    return out
