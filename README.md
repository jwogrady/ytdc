# ytdc

**Clean YouTube in one workflow — no guessing what you actually watch.**

![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)

Your subscriptions and likes are stale. You added channels years ago, hit "Like"
once, and forgot about them. The catch: YouTube's Data API can list and delete
your subscriptions and likes, but it **cannot read your watch history** — the one
signal that tells you what you actually care about. So you're stuck keeping the
clutter or blindly guessing what to cut.

ytdc bridges that gap. You export your watch history from Google Takeout (the only
place YouTube hands it over), and ytdc joins it against your live subscriptions and
likes to show you exactly which subs you never watch and which likes are dead
weight. Then it executes an unsubscribe/unlike plan that **runs dry-run by
default** — you preview everything before a single deletion happens.

## Why the Takeout detour?

The YouTube Data API has no endpoint for watch history. Full stop. The only
reliable source of "what did I actually watch" is a Google Takeout export of your
YouTube data (`watch-history.json`). ytdc is built entirely around bridging that
gap: it pulls your live subs and likes through the API, then joins them against
your Takeout history offline. That export is a one-time manual step, and it's the
whole premise — without it, there's nothing to reason from.

## Why not just unsubscribe in the YouTube UI, or write your own script?

**The YouTube UI** is fine for a one-off — dropping five channels you remember
subscribing to needs nothing installed. It breaks down for a bulk cleanup because
it shows your subscriptions but not whether you've watched a channel in the last
year, leaves no permanent backup before you act (and YouTube has no bulk
re-subscribe), and keeps no record of what you removed. Use the UI when you have
fewer than ~10 channels to prune and already know which ones.

**Rolling your own script** is a legitimate path if you're comfortable with Python
and OAuth — none of the pieces are rocket science. But you'd be writing the
installed-app OAuth flow and token persistence, pagination for `subscriptions.list`
and `videos.list`, dry-run safety, quota limiting, a resumable log so you don't
re-delete on a re-run, and error handling so one `403` doesn't abort 200 other
cleanups. You'd also discover the hard way that `subscriptions.delete` needs the
subscription *resource* id, not the channel id. ytdc has already paid that tax.

**Use ytdc when** you have 50+ subscriptions or likes to review, you want the
keep/cut decision backed by your real watch data, and you'd rather not build and
debug all that plumbing yourself.

## Requirements

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** (the package manager this project uses)
- A Unix shell and a Google account with YouTube activity

## Install

```bash
git clone https://github.com/jwogrady/ytdc.git
cd ytdc
uv sync
```

`uv sync` installs ytdc and its Google API dependencies, pinned in `uv.lock`.
Verify the CLI works:

```bash
uv run ytdc --help
```

You should see the subcommands: `auth`, `fetch-subs`, `fetch-likes`, `analyze`,
`execute`.

## One-time external setup

ytdc needs two things you set up once: your watch history, and a Google OAuth
credential.

### 1. Export your watch history from Google Takeout

1. Go to [takeout.google.com](https://takeout.google.com).
2. Click **Deselect all**, then select only **YouTube and YouTube Music**.
3. Under that entry, narrow the data to **history**. Either export format works —
   `analyze` accepts both the default **HTML** (`watch-history.html`) and **JSON**
   (`watch-history.json`), so you can leave the format as-is.
4. Download the export, unzip it, and find `watch-history.html` (or
   `watch-history.json`). Note its path — you'll pass it to `analyze`.

This is required because the API can't return watch history; Takeout is the only
source.

### 2. Create a Google Cloud OAuth credential

This lets ytdc call the YouTube Data API on your behalf.

1. At [console.cloud.google.com](https://console.cloud.google.com), create a
   project (any name).
2. **Enable the YouTube Data API v3** for that project.
3. Set up the **OAuth consent screen**: choose **External**, fill in an app name
   and your email, add the scope
   `https://www.googleapis.com/auth/youtube.force-ssl` (required to delete
   subscriptions and clear likes), and add your own Google account under **Test
   users**.
4. Create an **OAuth client ID** of type **Desktop app**, then **Download JSON**.
5. **Rename the downloaded file to exactly `client_secret.json` and place it in
   the ytdc repo root** (next to `pyproject.toml`).

> **This rename is not optional.** ytdc reads the filename `client_secret.json`
> directly — the long auto-generated name Google gives you
> (`client_secret_…apps.googleusercontent.com.json`) will not be found, and
> `ytdc auth` will fail with "Missing client_secret.json". The file is gitignored,
> so it stays local; never commit it.

## Usage

Once setup is done, the flow is: authenticate, back up your data, analyze it,
write a plan, and execute it.

| Step | Command | What it does |
|---|---|---|
| Authenticate | `uv run ytdc auth` | One-time OAuth; caches `data/token.json` |
| Back up subs | `uv run ytdc fetch-subs` | Writes `data/subscriptions.json` |
| Back up likes | `uv run ytdc fetch-likes` | Writes `data/likes.json` |
| Analyze | `uv run ytdc analyze --history <path>` | Joins backups against history → `data/analysis.json` |
| Preview | `uv run ytdc execute --plan data/plan.json` | Dry-run; zero API calls |
| Apply | `uv run ytdc execute --plan data/plan.json --execute` | Performs the removals |

### 1. Authenticate (once)

```bash
uv run ytdc auth
```

A browser window opens; sign in and approve access. The token is cached to
`data/token.json` so later commands don't prompt you again.

### 2. Back up your subscriptions and likes

```bash
uv run ytdc fetch-subs
uv run ytdc fetch-likes
```

These write `data/subscriptions.json` and `data/likes.json`. **Keep them** —
YouTube has no bulk re-subscribe, so these are your only record of what you had
before any cleanup.

### 3. Analyze against your history

Point `--history` at the `watch-history.json` from your Takeout export:

```bash
uv run ytdc analyze --history /path/to/watch-history.json
```

This joins your subs and likes against your watch history (no API calls) and
writes `data/analysis.json`. Each subscription and liked video is annotated with
`views`, `first_watched`, `last_watched`, and `watched`. This file is **not a
cleanup plan** — it's the data you'll use to make decisions.

### 4. Write your plan

ytdc does not decide what to delete — that's your call. Read `data/analysis.json`,
then hand-write `data/plan.json` in this shape:

```json
{
  "unsubscribe": ["UCxxxxxxxxxxxxxxxx", "UCyyyyyyyyyyyyyyyy"],
  "unlike": ["dQw4w9WgXcQ", "9bZkp7q19f0"]
}
```

Each `unsubscribe` entry is a channel id from `data/subscriptions.json`; each
`unlike` entry is a video id from `data/likes.json`.

> **Authoring the plan is manual today.** ytdc ships no code that generates
> `plan.json` — see the roadmap below.

### 5. Dry-run, then execute

Always preview first. Without `--execute`, `execute` prints exactly what *would*
be removed and makes **zero API calls** — nothing changes:

```bash
uv run ytdc execute --plan data/plan.json
```

When you're confident, add `--execute` to actually apply the plan. Removals are
logged to `data/execute-log.json` as they happen, so you can stop and resume
safely:

```bash
uv run ytdc execute --plan data/plan.json --execute
```

To cap a single run — for example, to stay under the daily quota — use `--limit`:

```bash
uv run ytdc execute --plan data/plan.json --execute --limit 50
```

The run stops after 50 successful removals; re-run later to continue, and it skips
anything already done.

### Safety properties

- **Dry-run is the default.** No `--execute` means no API calls at all.
- **`--limit N` caps removals per run**, counted by successful action.
- **Resumable.** `data/execute-log.json` tracks what's removed; re-runs skip it.
- **Errors don't abort.** A failed removal is skipped (not logged), so it retries
  on the next run — one bad item won't stop the rest.
- **Permanent backups.** Subs and likes are written before any cleanup.
- **Secrets stay local.** `client_secret.json` and `data/token.json` are
  gitignored; the token is written owner-only.

## Quota note

YouTube's Data API allows **10,000 units/day** by default. Each unsubscribe
(`subscriptions.delete`) and each unlike (`videos.rate`) costs roughly **50
units**, so a day of cleanup tops out around **200 removals**. For larger
cleanups, use `--limit` and let the resume log (`data/execute-log.json`) carry the
job across multiple days. These are Google's published quota figures; ytdc tracks
your removal count via `--limit` but does not measure API unit cost itself.

## Status and roadmap

ytdc is **v0.1.0** — pre-1.0 personal tooling with one maintainer (jwogrady), not
yet hardened for shared dependence. The risk profile for personal use is low: it's
dry-run by default, keeps permanent backups, and every destructive path in
`execute` is covered by tests.

**Shipped and tested.** The full command surface (`auth`, `fetch-subs`,
`fetch-likes`, `analyze`, `execute`) is implemented. **8 tests pass** (`uv run
pytest`), offline with no network — 2 covering history parsing and the subs/likes
join, 6 covering the execute path: dry-run safety, resume, `--limit`, API-error
continuation, and plan de-duplication.

**Honest gaps.** No CI, no tagged releases or published package, no LICENSE file
yet (until one is added, standard copyright applies), and a single maintainer. The
`auth` and `fetch-*` API paths are not yet under test.

**Not yet shipped.** Automatic plan generation. Today you read `analysis.json` and
hand-write `plan.json` yourself; ytdc ships no code that authors it. That's on the
roadmap, not in the box.

---

Author: jwogrady
