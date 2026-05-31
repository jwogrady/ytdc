"""Apply an approved cleanup plan: unsubscribe channels and clear likes.

Dry-run by default — prints what would change and makes zero API calls. Pass
``--execute`` to actually call ``subscriptions.delete`` and
``videos.rate(rating="none")``. Resumable: every removal is recorded in
``data/execute-log.json`` and skipped on re-runs, so a quota-limited cleanup
can span several days without repeating work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from ytdc.auth import build_youtube_service

PLAN_FILE = Path("data/plan.json")
EXECUTE_LOG_FILE = Path("data/execute-log.json")


def _load_plan(plan_file: Path) -> dict:
    """Load an approved plan as ``{unsubscribe: [...], unlike: [...]}``."""
    if not plan_file.exists():
        raise FileNotFoundError(
            f"Missing {plan_file}. Approve a plan first (see README)."
        )
    plan = json.loads(plan_file.read_text())
    return {
        "unsubscribe": list(plan.get("unsubscribe", [])),
        "unlike": list(plan.get("unlike", [])),
    }


def _load_log(log_file: Path) -> dict:
    """Load the resume log, or an empty one if this is the first run."""
    if log_file.exists():
        log = json.loads(log_file.read_text())
        return {
            "unsubscribed": list(log.get("unsubscribed", [])),
            "unliked": list(log.get("unliked", [])),
        }
    return {"unsubscribed": [], "unliked": []}


def _save_log(log_file: Path, log: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log, indent=2))


def _dedupe(items: list[str]) -> list[str]:
    """Drop duplicate ids while preserving order (a plan may list one twice)."""
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def _subscription_id_map(youtube) -> dict[str, str]:
    """Map ``channel_id`` -> subscription resource id for the current account.

    ``subscriptions.delete`` needs the subscription's own id, not the channel
    id the plan carries, so this is resolved live at execute time.
    """
    mapping: dict[str, str] = {}
    request = youtube.subscriptions().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            mapping[item["snippet"]["resourceId"]["channelId"]] = item["id"]
        request = youtube.subscriptions().list_next(request, response)
    return mapping


def cmd_execute(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc execute`` (dry-run unless ``--execute``)."""
    plan = _load_plan(args.plan)
    log = _load_log(EXECUTE_LOG_FILE)
    done_subs = set(log["unsubscribed"])
    done_likes = set(log["unliked"])

    planned_subs = _dedupe(plan["unsubscribe"])
    planned_likes = _dedupe(plan["unlike"])
    pending_subs = [c for c in planned_subs if c not in done_subs]
    pending_likes = [v for v in planned_likes if v not in done_likes]

    if not args.execute:
        print("DRY RUN — no changes made. Pass --execute to apply.")
        print(f"Would unsubscribe from {len(pending_subs)} channel(s):")
        for channel_id in pending_subs:
            print(f"  - {channel_id}")
        print(f"Would unlike {len(pending_likes)} video(s):")
        for video_id in pending_likes:
            print(f"  - {video_id}")
        already_done = (len(planned_subs) - len(pending_subs)) + (
            len(planned_likes) - len(pending_likes)
        )
        if already_done:
            print(f"({already_done} already done, per {EXECUTE_LOG_FILE})")
        return 0

    youtube = build_youtube_service()
    actions = 0

    def at_limit() -> bool:
        return args.limit is not None and actions >= args.limit

    sub_map = _subscription_id_map(youtube) if pending_subs else {}
    for channel_id in pending_subs:
        if at_limit():
            break
        sub_id = sub_map.get(channel_id)
        if sub_id is None:
            # Not currently subscribed (already removed or never subscribed):
            # record it as done without spending a delete call.
            print(f"  already not subscribed: {channel_id}")
            log["unsubscribed"].append(channel_id)
            _save_log(EXECUTE_LOG_FILE, log)
            continue
        try:
            youtube.subscriptions().delete(id=sub_id).execute()
        except HttpError as exc:
            # Leave it unlogged so a later run retries it.
            print(f"  failed to unsubscribe {channel_id}: {exc}", file=sys.stderr)
            continue
        actions += 1
        log["unsubscribed"].append(channel_id)
        _save_log(EXECUTE_LOG_FILE, log)
        print(f"  unsubscribed: {channel_id}")

    for video_id in pending_likes:
        if at_limit():
            break
        try:
            youtube.videos().rate(id=video_id, rating="none").execute()
        except HttpError as exc:
            print(f"  failed to unlike {video_id}: {exc}", file=sys.stderr)
            continue
        actions += 1
        log["unliked"].append(video_id)
        _save_log(EXECUTE_LOG_FILE, log)
        print(f"  unliked: {video_id}")

    print(f"Done. {actions} removal(s) this run.")
    if at_limit():
        print(f"Stopped at --limit {args.limit}. Re-run to continue.")
    return 0
