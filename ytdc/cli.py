"""Command-line interface for ytdc.

Dispatches subcommands via argparse. Running with no subcommand prints help.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ytdc import auth, execute, likes, report, subs


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser and register subcommands."""
    parser = argparse.ArgumentParser(
        prog="ytdc",
        description="YouTube Decrapifier — clean up subscriptions and likes.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    auth_parser = subparsers.add_parser(
        "auth", help="Run the OAuth flow once and cache the token."
    )
    auth_parser.set_defaults(func=auth.cmd_auth)

    fetch_subs_parser = subparsers.add_parser(
        "fetch-subs", help="Back up live subscriptions to data/subscriptions.json."
    )
    fetch_subs_parser.set_defaults(func=subs.cmd_fetch_subs)

    fetch_likes_parser = subparsers.add_parser(
        "fetch-likes", help="Back up liked videos to data/likes.json."
    )
    fetch_likes_parser.set_defaults(func=likes.cmd_fetch_likes)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Join subs + likes against Takeout history → data/analysis.json.",
    )
    analyze_parser.add_argument(
        "--history",
        required=True,
        type=Path,
        help="Path to the Takeout watch-history.json export.",
    )
    analyze_parser.set_defaults(func=report.cmd_analyze)

    execute_parser = subparsers.add_parser(
        "execute",
        help="Apply an approved plan (dry-run unless --execute is passed).",
    )
    execute_parser.add_argument(
        "--plan",
        type=Path,
        default=execute.PLAN_FILE,
        help="Path to the approved plan.json (default: data/plan.json).",
    )
    execute_parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform removals (default: dry-run, no API changes).",
    )
    execute_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max removals to perform this run (quota guard).",
    )
    execute_parser.set_defaults(func=execute.cmd_execute)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except (FileNotFoundError, auth.AuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
