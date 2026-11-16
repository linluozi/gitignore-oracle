"""Parse and match a single .gitignore line with git's wildmatch semantics.

Only the documented gitignore subset is implemented: `*`, `?`, `[...]`,
`**` (leading, middle, trailing), `!` negation, trailing `/` (directory
only), leading `/` (anchor), backslash escapes and the "trailing spaces are
ignored unless escaped" rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

_SEG_CACHE: dict[str, re.Pattern[str]] = {}


def _seg_regex(seg: str) -> re.Pattern[str]:
    cached = _SEG_CACHE.get(seg)
    if cached is not None:
        return cached
    out = ["(?s:"]
    i = 0
    n = len(seg)
    while i < n:
        c = seg[i]
        if c == "\\" and i + 1 < n:
            out.append(re.escape(seg[i + 1]))
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and seg[j] in "!^":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                out.append(r"\[")
            else:
                cls = seg[i + 1 : j]
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                cls = cls.replace("\\", "\\\\")
                out.append("[" + cls + "]")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    out.append(")")
    rx = re.compile("".join(out))
    _SEG_CACHE[seg] = rx
    return rx


def _match_segments(pat: tuple[str, ...], path: tuple[str, ...]) -> bool:
    n, m = len(pat), len(path)

    @lru_cache(maxsize=None)
    def go(i: int, j: int) -> bool:
        if i == n:
            return j == m
        if pat[i] == "**":
            if n == 1:
                return True  # `**` alone matches any path
            if i == n - 1:
                # `a/**` means "everything inside a", not `a` itself.
                return j < m
            if go(i + 1, j):  # zero directories
                return True
            return j < m and go(i, j + 1)  # one directory, recurse
        if j == m:
            return False
        if _seg_regex(pat[i]).fullmatch(path[j]) is None:
            return False
        return go(i + 1, j + 1)

    return go(0, 0)


def _strip_unescaped_trailing_spaces(text: str) -> str:
    while text.endswith(" "):
        k = len(text) - 1
        bs = 0
        while k - 1 - bs >= 0 and text[k - 1 - bs] == "\\":
            bs += 1
        if bs % 2 == 1:
            break
        text = text[:-1]
    return text


@dataclass(frozen=True)
class Pattern:
    raw: str          # line as git prints it in `check-ignore -v` (without newline)
    body: str         # same line with `!`, leading `/` and trailing `/` removed
    negated: bool
    dir_only: bool
    anchored: bool
    segments: tuple[str, ...] = field(default=())

    def matches(self, path: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        parts = tuple(path.split("/"))
        if not self.anchored:
            # A pattern without a slash matches the basename at any depth.
            return _match_segments(self.segments, parts[-1:])
        return _match_segments(self.segments, parts)


def parse_line(line: str, lineno: int = 0) -> Pattern | None:
    """Return a Pattern, or None for blank/comment lines. `lineno` unused."""
    text = line.rstrip("\n").rstrip("\r")
    if not text:
        return None
    if text[0] == "#":
        return None
    text = _strip_unescaped_trailing_spaces(text)
    if not text:
        return None
    if text.startswith("\\#"):
        text = text[1:]
    negated = False
    if text.startswith("!"):
        negated = True
        text = text[1:]
    elif text.startswith("\\!"):
        text = text[1:]
    if not text:
        return None
    dir_only = False
    if text.endswith("/"):
        # A trailing slash is the directory marker (a trailing `\/` would be
        # an escaped slash, which git rejects in practice; treat it literally).
        bs = 0
        k = len(text) - 2
        while k >= 0 and text[k] == "\\":
            bs += 1
            k -= 1
        if bs % 2 == 0:
            dir_only = True
            text = text[:-1]
    anchored = False
    if text.startswith("/"):
        anchored = True
        text = text[1:]
    if not text:
        return None
    anchored = anchored or "/" in text
    return Pattern(
        raw=_raw_for_display(line),
        body=text,
        negated=negated,
        dir_only=dir_only,
        anchored=anchored,
        segments=tuple(text.split("/")),
    )


def _raw_for_display(line: str) -> str:
    """Reproduce the pattern text as `git check-ignore -v` prints it."""
    text = line.rstrip("\n").rstrip("\r")
    text = _strip_unescaped_trailing_spaces(text)
    return text
