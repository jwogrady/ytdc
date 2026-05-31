"""Fetch and back up the authenticated user's liked videos.

As with subscriptions, ``data/likes.json`` is the permanent record of what was
liked before any cleanup clears those likes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ytdc.auth import build_youtube_service

LIKES_FILE = Path("data/likes.json")


def fetch_likes(youtube) -> list[dict]:
    """Return all liked videos, following pages.

    Each entry is ``{video_id, title, channel_id, channel_title}``.
    """
    likes: list[dict] = []
    request = youtube.videos().list(part="snippet", myRating="like", maxResults=50)
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            likes.append(
                {
                    "video_id": item["id"],
                    "title": snippet["title"],
                    "channel_id": snippet["channelId"],
                    "channel_title": snippet["channelTitle"],
                }
            )
        request = youtube.videos().list_next(request, response)
    return likes


def cmd_fetch_likes(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc fetch-likes``."""
    youtube = build_youtube_service()
    likes = fetch_likes(youtube)
    LIKES_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIKES_FILE.write_text(json.dumps(likes, indent=2))
    print(f"Fetched {len(likes)} liked videos → {LIKES_FILE}")
    return 0
