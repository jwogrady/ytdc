# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ytdc` ("YouTube Decrapifier") is a CLI that helps you prune stale YouTube
subscriptions and likes using your real watch history. The core constraint that
shapes the whole design: **the YouTube Data API cannot read watch history.** The
only source is a manual Google Takeout export. So ytdc pulls live subs/likes
through the API, then joins them *offline* against the Takeout file.

## Commands

```bash
uv sync                       # install deps (pinned in uv.lock)
uv run ytdc --help            # subcommands: auth, fetch-subs, fetch-likes, analyze, execute, subscribe
uv run pytest                 # full test suite (offline, no network)
uv run pytest tests/test_execute.py            # one file
uv run pytest tests/test_execute.py::test_name # one test
```

There is no linter/formatter configured.

## Pipeline (the commands form a strict order)

1. `auth` — interactive OAuth, caches `data/token.json` (the only command that opens a browser).
2. `fetch-subs` / `fetch-likes` — back up live data to `data/subscriptions.json` / `data/likes.json` via the API.
3. `analyze --history <path>` — offline join of those backups against the Takeout file → `data/analysis.json`. **No API calls.**
4. **The user hand-writes `data/plan.json`** (`{"unsubscribe": [channel_ids], "unlike": [video_ids]}`). ytdc ships no plan-generation code; `analyze` output is decision data, not a plan.
5. `execute --plan data/plan.json [--execute] [--limit N]` — dry-run by default; `--execute` performs removals.

## Architecture

`ytdc/cli.py` is the only entry point: argparse dispatches each subcommand to a
`cmd_*` handler in its module. The handler does I/O + printing; a pure,
service-injectable function next to it does the real work (e.g. `cmd_fetch_subs`
→ `fetch_subscriptions(youtube)`). Tests call the pure functions directly.

- `auth.py` — OAuth. Two entry points by intent: `get_credentials()` may launch the consent flow (used by `auth` only); `load_existing_credentials()` / `build_youtube_service()` **never** pop a browser and raise `AuthError` if not authenticated (used by fetch/execute). Scope is `youtube.force-ssl` (required to delete subs and clear likes). Tokens are written at `0600` via `os.open` to avoid a world-readable window.
- `history.py` — parses the Takeout export. Accepts **both JSON and HTML** (HTML is Takeout's default); the format is sniffed from the first non-whitespace char (`<` → HTML). Channels are attributed via `/channel/UC...` links; items without one (ads, deleted videos, some Shorts) are counted as `unattributable` and skipped. Output: `channel_id -> {name, views, first_watched, last_watched}`.
- `report.py` — `analyze`. Reads the two backups + history, annotates each sub/like with `views`/`first_watched`/`last_watched`/`watched`.
- `execute.py` — applies the plan. See below.
- `subscribe.py` — the inverse of execute's unsubscribe step (`subscribe`). Reads a file of channel `@handles`, resolves each via `channels.list(forHandle=...)`, skips ids already in the live subscription set, and calls `subscriptions.insert` on the rest. Dry-run by default (lists handles, **no API calls**). Idempotent — it diffs against live subs, so a quota-limited run resumes next day without a log. Reuses execute's `_describe_http_error` / `_is_quota_error`.
- `errors.py` — `InputError` for malformed user input. `cli.py:main` catches `FileNotFoundError`, `AuthError`, and `InputError` and prints `error: ...` with no traceback; anything else is a real bug and should surface.

## execute.py specifics (the riskiest module)

- **Resumable by design.** Every successful removal is appended to `data/execute-log.json` (`unsubscribed`/`unliked`) and `_save_log` is called *immediately after each one*, so a killed or quota-limited run never repeats work. Pending = planned − logged.
- **`subscriptions.delete` needs the subscription *resource* id, not the channel id** the plan carries. `_subscription_id_map()` resolves channel_id → sub_id live at execute time. A planned channel that isn't in the live map is logged as done without spending a delete (already unsubscribed).
- **Unlike** is `videos.rate(rating="none")`.
- **Quota handling:** `_QUOTA_REASONS` (`quotaExceeded`, `dailyLimitExceeded`) are hard stops for the day; the run breaks and tells the user to re-run tomorrow. Other `HttpError`s are logged per-item and skipped (item stays unlogged so it retries next run). `--limit` caps actions per run.
- Each `--execute` run writes a `last_run` block (finished_at, `stopped_reason` ∈ {completed, limit, quota, errors}, counts, pending, errors). A later dry-run prints the previous `last_run` summary.

## Conventions

- All output files live under `data/` (gitignored along with `client_secret*`, `token.json`, and Takeout exports). `client_secret.json` must be named exactly that in the repo root — the code reads that literal filename.
- Modules use `from __future__ import annotations`, module-level `Path` constants for file locations (overridable as function args for testing), and docstrings that explain *why* (the API/Takeout constraints), not just what.
- Tests are fully offline — they build tiny fixtures in `tmp_path` and pass fakes/paths into the pure functions. Keep new logic testable the same way (separate the API/IO boundary from the logic).

## scripts/

`scripts/subscribe-list.example.txt` is a sample input for `ytdc subscribe` —
one channel `@handle` per line. Copy it to `data/subscribe-list.txt` (gitignored)
and edit. There is no standalone script anymore; bulk-subscribe is the `subscribe`
subcommand.
