"""Parse a Google Takeout watch-history export into per-channel watch stats.

The YouTube Data API cannot read watch history, so the only source of "what you
actually watch" is a Takeout export. Takeout offers the history in **JSON** or
**HTML** (HTML is the default), and ``analyze`` accepts either — the format is
sniffed from the file's first non-whitespace character. Each watched item is
attributed to a channel via its ``/channel/UC...`` link; items without one (ads,
deleted videos, some Shorts) are counted as unattributable and skipped.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from ytdc.errors import InputError

# Channel IDs always start with "UC" followed by URL-safe base64 characters.
_CHANNEL_URL_RE = re.compile(r"/channel/(UC[\w-]+)")

# A normalized watch record: channel_id (None = unattributable), name, timestamp.
_Record = tuple[str | None, str, str | None]


def parse_watch_history(path: Path) -> tuple[dict[str, dict], int]:
    """Return ``(channels, unattributable_count)`` from a JSON or HTML export.

    ``channels`` maps each ``channel_id`` to
    ``{"name", "views", "first_watched", "last_watched"}``. Timestamps sort
    chronologically as text (ISO-8601 from JSON; normalized ISO from HTML).

    Raises :class:`InputError` if the file is not a recognizable Takeout export.
    """
    # utf-8-sig transparently strips a BOM, which would otherwise survive
    # lstrip() and break the format sniff below.
    text = Path(path).read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("<"):
        records = _records_from_html(text)
    else:
        records = _records_from_json(text, path)
    return _aggregate(records)


def _aggregate(records: list[_Record]) -> tuple[dict[str, dict], int]:
    """Fold normalized records into per-channel view counts and watch spans."""
    channels: dict[str, dict] = {}
    unattributable = 0
    for channel_id, name, watched_at in records:
        if channel_id is None:
            unattributable += 1
            continue
        stat = channels.get(channel_id)
        if stat is None:
            channels[channel_id] = {
                "name": name,
                "views": 1,
                "first_watched": watched_at,
                "last_watched": watched_at,
            }
        else:
            stat["views"] += 1
            if watched_at:
                if stat["first_watched"] is None or watched_at < stat["first_watched"]:
                    stat["first_watched"] = watched_at
                if stat["last_watched"] is None or watched_at > stat["last_watched"]:
                    stat["last_watched"] = watched_at
    return channels, unattributable


def _records_from_json(text: str, path: Path) -> list[_Record]:
    """Normalize a Takeout ``watch-history.json`` array into records."""
    try:
        entries = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise InputError(
            f"{path} is not a Takeout watch-history export (expected a JSON array)."
        )

    records: list[_Record] = []
    for entry in entries:
        if not isinstance(entry, dict):
            records.append((None, "", None))
            continue
        subtitles = entry.get("subtitles")
        if not subtitles:
            records.append((None, "", None))
            continue
        match = _CHANNEL_URL_RE.search(subtitles[0].get("url", ""))
        if not match:
            records.append((None, "", None))
            continue
        records.append(
            (match.group(1), subtitles[0].get("name", ""), entry.get("time") or None)
        )
    return records


# The data cell of each Takeout history entry (the sibling "...--text-right" and
# "...--caption" cells have different class suffixes and are intentionally skipped).
_HTML_CELL_RE = re.compile(
    r'content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>',
    re.S,
)
_HTML_CHANNEL_RE = re.compile(r'/channel/(UC[\w-]+)"[^>]*>([^<]*)</a>')
_HTML_TS_RE = re.compile(
    r"([A-Za-z]{3,9}) (\d{1,2}), (\d{4}), (\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)"
)


def _records_from_html(text: str) -> list[_Record]:
    """Normalize a Takeout ``watch-history.html`` document into records."""
    records: list[_Record] = []
    for cell in _HTML_CELL_RE.findall(text):
        channel = _HTML_CHANNEL_RE.search(cell)
        if not channel:
            records.append((None, "", None))
            continue
        channel_id = channel.group(1)
        name = html.unescape(channel.group(2).strip())
        records.append((channel_id, name, _parse_html_timestamp(cell)))
    return records


def _parse_html_timestamp(cell: str) -> str | None:
    """Extract and normalize the localized HTML timestamp to a sortable ISO string.

    Takeout renders e.g. ``May 31, 2026, 1:11:00 PM EDT``. The timezone
    abbreviation is dropped (every entry shares the account's zone, so ordering
    is unaffected) and the rest is parsed to ``YYYY-MM-DDTHH:MM:SS``. Returns
    None if no timestamp is found or it cannot be parsed.
    """
    match = _HTML_TS_RE.search(cell)
    if not match:
        return None
    month, day, year, hour, minute, second, meridiem = match.groups()
    # First 3 letters normalizes both "Sept"->"Sep" and full month names.
    stamp = f"{month[:3]} {day} {year} {hour}:{minute}:{second} {meridiem}"
    try:
        return datetime.strptime(stamp, "%b %d %Y %I:%M:%S %p").isoformat()
    except ValueError:
        return None
