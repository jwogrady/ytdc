"""Parse a Google Takeout ``watch-history.json`` into per-channel watch stats.

The YouTube Data API cannot read watch history, so the only source of "what you
actually watch" is a Takeout export. Each entry attributes a watched video to a
channel via ``subtitles[0].url`` (``.../channel/UC...``); entries without that
(ads, deleted videos, some Shorts) are counted as unattributable and skipped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ytdc.errors import InputError

# Channel IDs always start with "UC" followed by URL-safe base64 characters.
_CHANNEL_URL_RE = re.compile(r"/channel/(UC[\w-]+)")


def parse_watch_history(path: Path) -> tuple[dict[str, dict], int]:
    """Return ``(channels, unattributable_count)``.

    ``channels`` maps each ``channel_id`` to
    ``{"name", "views", "first_watched", "last_watched"}``. Timestamps are the
    raw ISO-8601 strings from Takeout, which sort chronologically as text.

    Raises :class:`InputError` if the file is not valid JSON or is not the
    expected top-level array (e.g. ``--history`` pointed at the wrong file).
    """
    try:
        entries = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise InputError(
            f"{path} is not a Takeout watch-history export (expected a JSON array)."
        )

    channels: dict[str, dict] = {}
    unattributable = 0

    for entry in entries:
        if not isinstance(entry, dict):
            unattributable += 1
            continue
        subtitles = entry.get("subtitles")
        if not subtitles:
            unattributable += 1
            continue
        match = _CHANNEL_URL_RE.search(subtitles[0].get("url", ""))
        if not match:
            unattributable += 1
            continue

        channel_id = match.group(1)
        watched_at = entry.get("time") or None
        stat = channels.get(channel_id)
        if stat is None:
            channels[channel_id] = {
                "name": subtitles[0].get("name", ""),
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
