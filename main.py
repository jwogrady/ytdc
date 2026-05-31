"""Thin entry point delegating to the ytdc CLI."""

from ytdc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
