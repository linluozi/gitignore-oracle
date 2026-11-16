"""gitignore-oracle: explain and verify .gitignore decisions.

Public API::

    GitIgnore(root).check("path/to/file") -> Decision
    GitIgnore(root).audit()               -> unwinnable-rule report
"""
from .engine import Decision, GitIgnore, Rule, parse_gitignore_text, expand_witness
from .pattern import Pattern, parse_line

__all__ = [
    "Decision", "GitIgnore", "Rule", "Pattern", "parse_line",
    "parse_gitignore_text", "expand_witness",
]
__version__ = "0.1.0"
