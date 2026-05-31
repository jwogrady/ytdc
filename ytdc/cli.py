"""Command-line interface for ytdc.

Dispatches subcommands via argparse. Running with no subcommand prints help.
"""

from __future__ import annotations

import argparse
import sys

from ytdc import auth, subs


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
