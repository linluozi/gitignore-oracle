import pytest

from gitignore_oracle.pattern import parse_line


def m(pattern, path, is_dir=False):
    p = parse_line(pattern)
    assert p is not None
    return p.matches(path, is_dir)


def test_glob_does_not_cross_slash():
    assert m("*.log", "a.log")
    assert m("*.log", "sub/a.log")
    assert not m("a/*.log", "a/b/c.log")
    assert m("a/*.log", "a/c.log")


def test_question_mark():
    assert m("a?c", "abc")
    assert not m("a?c", "a/c")
    assert not m("a?c", "ac")


def test_character_class():
    assert m("[abc]*.py", "b1.py")
    assert not m("[abc]*.py", "d1.py")
    assert m("[!abc]*.py", "d1.py")
    assert not m("[!abc]*.py", "a1.py")


def test_double_star_middle():
    assert m("foo/**/bar", "foo/bar")
    assert m("foo/**/bar", "foo/x/bar")
    assert m("foo/**/bar", "foo/x/y/bar")
    assert not m("foo/**/bar", "other/foo/bar")


def test_double_star_leading():
    assert m("**/deep", "deep")
    assert m("**/deep", "z/deep")
    assert m("**/*.pyc", "a/b/c.pyc")


def test_double_star_trailing():
    assert m("x/**", "x/y")
    assert m("x/**", "x/y/z")
    assert not m("x/**", "x")


def test_anchored_pattern():
    assert m("/root.txt", "root.txt")
    assert not m("/root.txt", "sub/root.txt")
    assert not m("doc/frotz", "a/doc/frotz")


def test_dir_only():
    p = parse_line("build/")
    assert p.dir_only
    assert p.matches("build", True)
    assert not p.matches("build", False)
    assert not p.matches("sub/build", False)


def test_negation_flag():
    p = parse_line("!keep.log")
    assert p.negated
    assert p.body == "keep.log"
    assert p.matches("keep.log", False)


def test_escaped_comment_and_bang():
    p = parse_line("\\#literal")
    assert p is not None and not p.negated
    assert p.matches("#literal", False)
    p = parse_line("\\!bang")
    assert p is not None and not p.negated
    assert p.matches("!bang", False)


def test_comment_and_blank():
    assert parse_line("# comment") is None
    assert parse_line("") is None


def test_trailing_space_rules():
    assert m("trailing\\ ", "trailing ", False)
    p = parse_line("trailing ")
    assert p.body == "trailing"


def test_escaped_star_is_literal():
    assert m("a\\*b", "a*b")
    assert not m("a\\*b", "axb")


def test_invalid_class_is_literal():
    assert m("a[b", "a[b")


@pytest.mark.parametrize(
    "pattern,path",
    [
        ("a/**/b/**/c", "a/b/c"),
        ("a/**/b/**/c", "a/x/y/b/z/c"),
        ("**/a/**", "a/x"),
        ("**/a/**", "q/a/x/y"),
    ],
)
def test_double_star_combinations(pattern, path):
    assert m(pattern, path)
