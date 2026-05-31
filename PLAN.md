# ytdc — YouTube Decrapifier

## Context

You want to declutter YouTube on two axes — **unsubscribe** from channels you don't
actually watch, **and unlike** videos you don't actually care about — keeping only what
matches the channels you genuinely watch. The blocker: YouTube's Data API can list/delete
subscriptions and list/clear likes (with OAuth) but **cannot read your watch history** —
Google removed that years ago. The only reliable source of "what you actually watch" is a
**Google Takeout** export (`watch-history.json`).

So ytdc is a small CLI that (1) pulls your live subscriptions **and liked videos** via the
API, (2) parses your Takeout watch history, and (3) joins them into an annotated report.
**Claude reads that report and proposes a concrete keep/unsubscribe/unlike plan; you approve
it; then ytdc executes both the unsubscribes and the unlikes** — defaulting to dry-run, with
an explicit `--execute` gate.

API calls used:
- `subscriptions.list` / `subscriptions.delete` — list & remove subscriptions.
- `videos.list(myRating=like)` / `videos.rate(rating="none")` — list & remove likes.

## One-time setup you'll need to do (outside the code)

1. **Takeout export** → https://takeout.google.com → select only *YouTube and YouTube
   Music* → *history* → JSON format → download. Extract `watch-history.json`.
2. **OAuth credentials** → https://console.cloud.google.com →
   - Create/select a project → enable **YouTube Data API v3**.
   - OAuth consent screen: External, add yourself as a Test User.
   - Create **OAuth client ID → Desktop app** → download as `client_secret.json`.
   - Scope used: `https://www.googleapis.com/auth/youtube.force-ssl` (required to delete subs).

(I'll write a step-by-step version of this into the README.)

## Architecture (flat modules in repo root)

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | add deps: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` |
| `ytdc/__init__.py` | package marker |
| `ytdc/auth.py` | OAuth flow; caches token at `data/token.json`, reads `client_secret.json` |
| `ytdc/history.py` | parse `watch-history.json` → per-channel `{channel_id, name, views, first/last watched}` |
| `ytdc/subs.py` | `subscriptions.list(mine=True)` paginated → list of `{channel_id, title}` |
| `ytdc/likes.py` | `videos.list(myRating=like)` paginated → list of `{video_id, title, channel_id, channel_title}` |
| `ytdc/report.py` | join subs + likes × history → `data/analysis.json` (subs & likes annotated with watch stats) |
| `ytdc/execute.py` | read approved `data/plan.json`; `subscriptions.delete` + `videos.rate(rating=none)`; log results |
| `ytdc/cli.py` | argparse dispatch |
| `main.py` | thin entry → `ytdc.cli:main` |
| `README.md` | setup + usage |
| `.gitignore` | add `data/`, `client_secret.json`, `*.json` data artifacts |

## CLI commands

- `ytdc auth` — run OAuth once, cache token.
- `ytdc fetch-subs` — write `data/subscriptions.json` (permanent backup; YouTube has **no bulk
  re-subscribe**, so this is your record of what you were subscribed to).
- `ytdc fetch-likes` — write `data/likes.json` (permanent backup of liked videos for the same reason).
- `ytdc analyze --history path/to/watch-history.json` — join subs + likes + history → `data/analysis.json`.
  Each subscribed channel and each liked video gets: `views`, `last_watched`, `first_watched`, `watched` flag.
- `ytdc execute --plan data/plan.json` — **dry-run by default** (prints the unsubscribe + unlike lists,
  changes nothing). Add `--execute` to actually run. Add `--limit N` for quota. Resumable: skips items
  already removed (logged in `data/execute-log.json`).

## How the approval gate works (the part you asked for)

1. You run `auth`, `fetch-subs`, `fetch-likes`, `analyze`.
2. **I read `data/analysis.json`** — your real subs and likes with watch counts — and propose, here
   in chat, exactly which channels to unsubscribe and which videos to unlike (and why). We adjust together.
3. On your OK, I write the approved lists to `data/plan.json` (`{ "unsubscribe": [...channel_ids],
   "unlike": [...video_ids] }`).
4. You run `ytdc execute --plan data/plan.json --execute`.

No threshold is hardcoded — the keep/kill decision is a judgment call I make from your actual
data and you sign off on.

## Data join detail

Takeout entries look like:
`{"title":"Watched <video>","subtitles":[{"name":"Chan","url":".../channel/UC..."}],"time":"..."}`
Channel ID (`UC...`) is parsed from `subtitles[0].url` and joins directly against
`subscriptions.list`'s `snippet.resourceId.channelId`. Entries lacking `subtitles`
(deleted videos, ads, Shorts surfacing) are skipped and counted as "unattributable".

## Quota note

Default API quota is 10,000 units/day. `subscriptions.delete` and `videos.rate` each cost
**50 units** → ~200 removals/day combined. `--limit` + the resumable log let large cleanups
span multiple days without re-deleting.

## Safety

- `execute` is dry-run unless `--execute` is passed.
- `data/subscriptions.json` and `data/likes.json` are permanent pre-change backups.
- `data/`, `client_secret.json`, and `token.json` are gitignored (personal data + secrets).

## Verification

1. `uv sync` installs deps cleanly.
2. `ytdc analyze` against a sample `watch-history.json` produces a well-formed `data/analysis.json`
   (unit-testable parse with a tiny fixture, no network).
3. `ytdc execute --plan ...` (no `--execute`) prints the kill-list and makes **zero** API delete calls.
4. End-to-end against your real account once you've done the Takeout + OAuth setup.
