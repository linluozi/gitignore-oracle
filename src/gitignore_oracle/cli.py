"""Command line interface for gitignore-oracle."""
from __future__ import annotations

import argparse
import json
import sys

from .engine import GitIgnore
from .gitdiff import verify_repo


def _print_decision(dec, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dec.to_dict(), ensure_ascii=False))
        return
    tag = "IGNORED" if dec.ignored else ("RE-INCLUDED" if dec.matched else "TRACKED")
    print(f"{dec.path}\t{tag}\t{dec.reason}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gitignore-oracle",
        description="Explain .gitignore decisions and verify them against real git.",
    )
    ap.add_argument("--root", default=".", help="work tree root (default: .)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="decide one or more paths")
    c.add_argument("paths", nargs="+")
    c.add_argument("--dir", action="store_true", help="treat paths as directories")
    c.add_argument("--json", action="store_true")

    w = sub.add_parser("why", help="explain the deciding rule for one path")
    w.add_argument("path")
    w.add_argument("--dir", action="store_true")
    w.add_argument("--json", action="store_true")

    a = sub.add_parser("audit", help="find negation rules that can never fire")
    a.add_argument("--json", action="store_true")

    v = sub.add_parser("verify", help="differential test against git check-ignore")
    v.add_argument("--json", action="store_true")
    v.add_argument("--max-witnesses", type=int, default=20)

    args = ap.parse_args(argv)
    gi = GitIgnore(args.root)

    if args.cmd in ("check", "why"):
        paths = args.paths if args.cmd == "check" else [args.path]
        failed = False
        for p in paths:
            dec = gi.check(p, is_dir=True if args.dir else None)
            _print_decision(dec, args.json)
            # exit 1 means "at least one path is ignored", like git check-ignore
            failed = failed or dec.ignored
        return 1 if failed else 0

    if args.cmd == "audit":
        report = gi.audit()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"root: {report['root']}")
            print(f"rule files: {len(report['files'])}  rules: {report['total_rules']}  "
                  f"negations: {report['negations']}")
            for f in report["findings"]:
                d = f["decided_by"]
                print(f"{f['kind']}: {f['rule']['source']}:{f['rule']['line']} "
                      f"{f['rule']['pattern']} -> witness {f['witness']!r} "
                      f"decided by {d['source']}:{d['line']} {d['pattern']}")
            if not report["findings"]:
                print("no dead negation rules found")
        return 0

    if args.cmd == "verify":
        report = verify_repo(args.root)
        report["mismatches"] = report["mismatches"][: args.max_witnesses]
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(f"{status}: {report['files']} files + {report['dirs']} dirs = "
                  f"{report['paths']} paths, {report['git_matched']} matched by git "
                  f"({report['git_ignored']} ignored), "
                  f"{len(report['mismatches'])} mismatches")
            for m in report["mismatches"]:
                print(f"  {m['kind']}: {m['path']} engine={m['engine']} git={m['git']}")
        return 0 if report["ok"] else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
