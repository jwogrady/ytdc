"""Error types that the CLI reports cleanly (no traceback)."""

from __future__ import annotations


class InputError(Exception):
    """A user-provided input file is missing, malformed, or the wrong shape."""
