"""A .gitignore decision engine that reports *which rule* decided a path.

The public surface is intentionally small::

    from gitignore_oracle import GitIgnore
    gi = GitIgnore("/path/to/repo")
    gi.check("build/out.txt").ignored        # -> True
    gi.why("build/out.txt").source           # -> ".gitignore"
    gi.why("build/out.txt").line             # -> 3
    gi.why("build/out.txt").pattern          # -> "build/"

Semantics follow git's own description of gitignore precedence: the deepest
.gitignore wins, the last matching line inside one file wins, and a file
cannot be re-included when a parent directory is excluded (git never descends
into an excluded directory, so the re-inclusion rule is simply unreachable).
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from .pattern import Pattern, parse_line

__all__ = ["Decision", "GitIgnore", "Rule", "parse_gitignore_text"]


@dataclass(frozen=True)
class Rule:
    pattern: Pattern
    source: str   # repo-relative path of the file that contains the rule
    line: int     # 1-based

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "line": self.line,
            "pattern": self.pattern.raw,
            "negated": self.pattern.negated,
            "dir_only": self.pattern.dir_only,
        }


@dataclass(frozen=True)
class Decision:
    path: str
    ignored: bool
    matched: bool
    source: str | None = None
    line: int | None = None
    pattern: str | None = None
    via: str | None = None   # excluded ancestor directory, if any

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "ignored": self.ignored,
            "matched": self.matched,
            "source": self.source,
            "line": self.line,
            "pattern": self.pattern,
            "via": self.via,
        }

    @property
    def reason(self) -> str:
        if not self.matched:
            return "no rule matched"
        what = "ignored" if self.ignored else "re-included"
        where = f"{self.source}:{self.line} ({self.pattern})"
        if self.via:
            return f"{what} via excluded parent directory {self.via!r} by {where}"
        return f"{what} by {where}"


def parse_gitignore_text(text: str, source: str = ".gitignore") -> list[Rule]:
    rules = []
    for i, line in enumerate(text.splitlines(), 1):
        pat = parse_line(line, i)
        if pat is not None:
            rules.append(Rule(pattern=pat, source=source, line=i))
    return rules


class GitIgnore:
    """Decision engine rooted at a work tree (or any directory tree)."""

    def __init__(self, root: str | Path, info_exclude: bool = True):
        self.root = Path(root)
        self._cache: dict[str, list[Rule]] = {}
        self.info_rules: list[Rule] = []
        if info_exclude:
            info = self.root / ".git" / "info" / "exclude"
            if info.is_file():
                self.info_rules = parse_gitignore_text(
                    info.read_text(encoding="utf-8", errors="surrogateescape"),
                    source=".git/info/exclude",
                )

    # -- rule loading ---------------------------------------------------
    def _rules(self, reldir: str) -> list[Rule]:
        cached = self._cache.get(reldir)
        if cached is not None:
            return cached
        if reldir:
            source = f"{reldir}/.gitignore"
        else:
            source = ".gitignore"
        path = self.root / source
        if path.is_file():
            rules = parse_gitignore_text(
                path.read_text(encoding="utf-8", errors="surrogateescape"),
                source=source,
            )
        else:
            rules = []
        self._cache[reldir] = rules
        return rules

    def _all_rule_files(self) -> list[str]:
        out = []
        for p in sorted(self.root.rglob(".gitignore")):
            rel = p.relative_to(self.root).as_posix()
            if ".git" in rel.split("/")[:-1]:
                continue
            out.append(rel)
        return out

    # -- decision -------------------------------------------------------
    def _decide_here(self, rel: str, is_dir: bool) -> Rule | None:
        parts = rel.split("/")
        for k in range(len(parts) - 1, -1, -1):
            base = "/".join(parts[:k])
            rel_to = "/".join(parts[k:])
            if not rel_to:
                continue
            for rule in reversed(self._rules(base)):
                if rule.pattern.matches(rel_to, is_dir):
                    return rule
        for rule in reversed(self.info_rules):
            if rule.pattern.matches(rel, is_dir):
                return rule
        return None

    def check(self, path: str, is_dir: bool | None = None) -> Decision:
        rel = path.replace("\\", "/").strip("/")
        if rel.startswith("./"):
            rel = rel[2:]
        if rel in ("", "."):
            return Decision(path=rel, ignored=False, matched=False)
        if is_dir is None:
            fs = self.root / rel
            is_dir = fs.is_dir() if fs.exists() else rel.endswith("/")
        parts = rel.split("/")
        # An excluded parent directory ends the walk: git cannot re-include
        # anything below it, no matter what a nested .gitignore says.
        for i in range(1, len(parts)):
            anc = "/".join(parts[:i])
            rule = self._decide_here(anc, True)
            if rule is not None and not rule.pattern.negated:
                return Decision(
                    path=rel, ignored=True, matched=True,
                    source=rule.source, line=rule.line,
                    pattern=rule.pattern.raw, via=anc,
                )
        rule = self._decide_here(rel, bool(is_dir))
        if rule is None:
            return Decision(path=rel, ignored=False, matched=False)
        return Decision(
            path=rel,
            ignored=not rule.pattern.negated,
            matched=True,
            source=rule.source,
            line=rule.line,
            pattern=rule.pattern.raw,
        )

    def why(self, path: str, is_dir: bool | None = None) -> Decision:
        return self.check(path, is_dir)

    # -- static analysis ------------------------------------------------
    def audit(self) -> dict:
        """Find negation rules that can never fire, with a concrete witness.

        Two kinds are reported, both of which are provable from git's own
        precedence rules:

        * ``dead_by_parent``: the witness has an excluded ancestor directory,
          so git never descends to the file the negation tries to re-include.
        * ``dead_by_later_ignore``: a later rule in the same file ignores the
          witness, so this negation is always overridden.
        """
        rule_files = self._all_rule_files()
        total_rules = 0
        negations = 0
        skipped_non_literal = 0
        findings: list[dict] = []
        for source in rule_files:
            # A .gitignore inside an excluded directory is never read by git.
            if self.check(source, is_dir=False).ignored:
                continue
            rules = self._rules(posixpath.dirname(source) if "/" in source else "")
            for rule in rules:
                total_rules += 1
                if not rule.pattern.negated:
                    continue
                negations += 1
                # A wildcard negation matches many paths; one dead witness is
                # not proof that the whole rule is dead. Only literal rules
                # (which match exactly one path) are reported as dead.
                if not _is_literal(rule.pattern.body):
                    skipped_non_literal += 1
                    continue
                base = posixpath.dirname(rule.source)
                for witness_rel in expand_witness(rule.pattern):
                    full = posixpath.join(base, witness_rel) if base else witness_rel
                    dec = self.check(
                        full, is_dir=rule.pattern.dir_only or None
                    )
                    if not dec.matched:
                        continue
                    if dec.ignored and dec.via:
                        findings.append({
                            "kind": "dead_by_parent",
                            "rule": rule.to_dict(),
                            "witness": full,
                            "decided_by": {
                                "source": dec.source, "line": dec.line,
                                "pattern": dec.pattern, "via": dec.via,
                            },
                        })
                        break
                    if dec.ignored and not dec.via and (
                        dec.source != rule.source or dec.line != rule.line
                    ):
                        kind = ("dead_by_later_ignore"
                                if dec.source == rule.source and dec.line > rule.line
                                else "dead_by_other_ignore")
                        findings.append({
                            "kind": kind,
                            "rule": rule.to_dict(),
                            "witness": full,
                            "decided_by": {
                                "source": dec.source, "line": dec.line,
                                "pattern": dec.pattern,
                            },
                        })
                        break
        counts: dict[str, int] = {}
        for f in findings:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        return {
            "root": str(self.root),
            "files": rule_files,
            "total_rules": total_rules,
            "negations": negations,
            "findings": findings,
            "counts": counts,
            "skipped_non_literal_negations": skipped_non_literal,
        }


def _is_literal(body: str) -> bool:
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if c in "*?[":
            return False
        i += 1
    return True


def _expand_segment(seg: str) -> list[str]:
    if seg == "**":
        return ["w", "w/q"]
    out = []
    for choice in ("w", "a"):
        chars = []
        i = 0
        while i < len(seg):
            c = seg[i]
            if c == "\\" and i + 1 < len(seg):
                chars.append(seg[i + 1])
                i += 2
            elif c == "*":
                chars.append(choice)
                i += 1
            elif c == "?":
                chars.append("q")
                i += 1
            elif c == "[":
                j = seg.find("]", i + 1)
                if j < 0:
                    chars.append("[")
                    i += 1
                else:
                    cls = seg[i + 1 : j]
                    if cls.startswith("!"):
                        chars.append("z")
                    else:
                        chars.append(cls[0] if cls else "a")
                    i = j + 1
            else:
                chars.append(c)
                i += 1
        out.append("".join(chars))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


def expand_witness(pattern: Pattern, limit: int = 8) -> list[str]:
    """Turn a pattern into concrete relative paths that it matches."""
    segs = pattern.body.split("/")
    combos: list[list[str]] = [[]]
    for seg in segs:
        values = _expand_segment(seg)
        combos = [c + [v] for c in combos for v in values][:limit]
    return ["/".join(c) for c in combos if c and c[-1]]
