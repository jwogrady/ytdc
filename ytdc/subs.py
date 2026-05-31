"""Fetch and back up the authenticated user's YouTube subscriptions.

YouTube has no bulk re-subscribe, so ``data/subscriptions.json`` is the
permanent record of what you were subscribed to before any cleanup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ytdc.auth import build_youtube_service

SUBSCRIPTIONS_FILE = Path("data/subscriptions.json")


def fetch_subscriptions(youtube) -> list[dict]:
    """Return all subscriptions as ``{channel_id, title}``, following pages."""
    subs: list[dict] = []
    request = youtube.subscriptions().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            subs.append(
                {
                    "channel_id": snippet["resourceId"]["channelId"],
                    "title": snippet["title"],
                }
            )
        request = youtube.subscriptions().list_next(request, response)
    return subs


def cmd_fetch_subs(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc fetch-subs``."""
    youtube = build_youtube_service()
    subs = fetch_subscriptions(youtube)
    SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIPTIONS_FILE.write_text(json.dumps(subs, indent=2))
    print(f"Fetched {len(subs)} subscriptions → {SUBSCRIPTIONS_FILE}")
    return 0
