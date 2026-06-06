"""Subscribe to channels listed by @handle in a file.

The mirror image of execute's unsubscribe step: ytdc can now rebuild a
subscription set (or act on a curated list of channels) as well as prune one.
Reads a file of channel ``@handles``, resolves each to a channel id, skips any
already subscribed, and inserts the rest.

Dry-run by default — lists the handles to be processed and makes zero API
calls (resolution happens only under ``--execute``). Idempotent: a re-run
subscribes only to what is still missing, so a quota-limited run resumes
safely on the next day without needing a log.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from ytdc.auth import build_youtube_service
from ytdc.execute import _describe_http_error, _is_quota_error

SUBSCRIBE_LIST_FILE = Path("data/subscribe-list.txt")

# subscriptions.insert returns this 400 reason when the account is already
# subscribed; treat it as a no-op success rather than an error.
_DUPLICATE_REASON = "subscriptionDuplicate"


def read_handles(path: Path) -> list[str]:
    """Parse a handle-per-line file, dropping blanks, comments, and leading @.

    Duplicates are removed while preserving first-seen order.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. List one channel @handle per line "
            "(see scripts/subscribe-list.example.txt)."
        )
    handles: list[str] = []
    seen: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        handle = line.lstrip("@")
        if handle not in seen:
            seen.add(handle)
            handles.append(handle)
    return handles


def resolve_handle(youtube, handle: str) -> tuple[str, str] | None:
    """Return ``(channel_id, title)`` for an ``@handle``, or None if unknown."""
    items = (
        youtube.channels()
        .list(part="id,snippet", forHandle=handle)
        .execute()
        .get("items", [])
    )
    if not items:
        return None
    return items[0]["id"], items[0]["snippet"]["title"]


def subscribed_channel_ids(youtube) -> set[str]:
    """Channel ids the account is currently subscribed to (all pages).

    Fetched once up front so the run can skip existing subscriptions without a
    per-channel lookup, which also makes a re-run naturally resumable.
    """
    ids: set[str] = set()
    request = youtube.subscriptions().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            ids.add(item["snippet"]["resourceId"]["channelId"])
        request = youtube.subscriptions().list_next(request, response)
    return ids


def _subscribe(youtube, channel_id: str) -> None:
    youtube.subscriptions().insert(
        part="snippet",
        body={
            "snippet": {
                "resourceId": {"kind": "youtube#channel", "channelId": channel_id}
            }
        },
    ).execute()


def cmd_subscribe(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc subscribe`` (dry-run unless ``--execute``)."""
    handles = read_handles(args.list)

    if not args.execute:
        print("DRY RUN — no changes made. Pass --execute to subscribe.")
        print(f"Would resolve and subscribe up to {len(handles)} channel(s):")
        for handle in handles:
            print(f"  - @{handle}")
        return 0

    youtube = build_youtube_service()
    current = subscribed_channel_ids(youtube)

    subscribed = 0
    already = 0
    missing: list[str] = []
    errors: list[dict] = []

    for handle in handles:
        resolved = resolve_handle(youtube, handle)
        if resolved is None:
            missing.append(handle)
            print(f"  ? @{handle}: handle not found", file=sys.stderr)
            continue
        channel_id, title = resolved
        if channel_id in current:
            already += 1
            print(f"  = {title}: already subscribed")
            continue
        try:
            _subscribe(youtube, channel_id)
        except HttpError as exc:
            detail = _describe_http_error(exc)
            if detail.get("reason") == _DUPLICATE_REASON:
                already += 1
                print(f"  = {title}: already subscribed")
                continue
            errors.append({"handle": handle, **detail})
            print(
                f"  failed to subscribe {title}: {detail['message']}",
                file=sys.stderr,
            )
            if _is_quota_error(detail):
                print(
                    "Stopped: YouTube API quota exhausted for today. "
                    "Re-run tomorrow to continue."
                )
                break
            continue
        current.add(channel_id)
        subscribed += 1
        print(f"  subscribed: {title}")

    print(
        f"Done. {subscribed} new, {already} already subscribed, "
        f"{len(missing)} unresolved, {len(errors)} error(s)."
    )
    if missing:
        print("Unresolved handles: " + ", ".join("@" + h for h in missing))
    return 0
