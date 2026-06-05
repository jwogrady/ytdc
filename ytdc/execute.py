"""Apply an approved cleanup plan: unsubscribe channels and clear likes.

Dry-run by default — prints what would change and makes zero API calls. Pass
``--execute`` to actually call ``subscriptions.delete`` and
``videos.rate(rating="none")``. Resumable: every removal is recorded in
``data/execute-log.json`` and skipped on re-runs, so a quota-limited cleanup
can span several days without repeating work.

Each ``--execute`` run also writes a ``last_run`` block to the log recording
when it finished, how much it changed, why it stopped (``completed``, ``limit``,
``quota``, or ``errors``), how much remains, and the details of any API failures
— so a partial run explains itself without spelunking the API output.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError

from ytdc.auth import build_youtube_service

PLAN_FILE = Path("data/plan.json")
EXECUTE_LOG_FILE = Path("data/execute-log.json")

# 403 reason codes that mean the daily quota is gone for good (today): no point
# retrying the remaining items this run. Transient ones (rateLimitExceeded) are
# recorded but not treated as a hard stop.
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


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
        loaded = {
            "unsubscribed": list(log.get("unsubscribed", [])),
            "unliked": list(log.get("unliked", [])),
        }
        if "last_run" in log:
            loaded["last_run"] = log["last_run"]
        return loaded
    return {"unsubscribed": [], "unliked": []}


def _describe_http_error(exc: HttpError) -> dict:
    """Pull the useful fields out of an ``HttpError`` for the run log.

    Returns ``{status, reason, message}`` where ``reason`` is the API's machine
    code (e.g. ``"quotaExceeded"``) when present, falling back to ``None``.
    """
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        pass
    reason = None
    message = str(exc)
    try:
        content = exc.content
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        payload = json.loads(content).get("error", {})
        message = payload.get("message", message)
        details = payload.get("errors") or []
        if details:
            reason = details[0].get("reason")
    except (ValueError, AttributeError):
        pass
    return {"status": status, "reason": reason, "message": message}


def _is_quota_error(detail: dict) -> bool:
    """True when the failure means today's quota is exhausted (hard stop)."""
    return detail.get("reason") in _QUOTA_REASONS


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
        last = log.get("last_run")
        if last:
            errs = last.get("errors") or []
            tail = f", {len(errs)} error(s)" if errs else ""
            print(
                f"Last execute run ({last.get('finished_at', '?')}): "
                f"{last.get('unsubscribed_this_run', 0)} unsubscribed, "
                f"{last.get('unliked_this_run', 0)} unliked, "
                f"stopped={last.get('stopped_reason', '?')}{tail}."
            )
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
    subs_done = 0
    likes_done = 0
    run_errors: list[dict] = []
    stopped_reason: str | None = None

    def at_limit() -> bool:
        return args.limit is not None and actions >= args.limit

    def record_error(item_id: str, action: str, exc: HttpError) -> bool:
        """Log an API failure; return True if it's a hard quota stop."""
        detail = _describe_http_error(exc)
        run_errors.append({"id": item_id, "action": action, **detail})
        # Leave the item unlogged so a later run retries it.
        print(f"  failed to {action} {item_id}: {detail['message']}", file=sys.stderr)
        return _is_quota_error(detail)

    sub_map = _subscription_id_map(youtube) if pending_subs else {}
    for channel_id in pending_subs:
        if at_limit():
            stopped_reason = "limit"
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
            if record_error(channel_id, "unsubscribe", exc):
                stopped_reason = "quota"
                break
            continue
        actions += 1
        subs_done += 1
        log["unsubscribed"].append(channel_id)
        _save_log(EXECUTE_LOG_FILE, log)
        print(f"  unsubscribed: {channel_id}")

    if stopped_reason != "quota":
        for video_id in pending_likes:
            if at_limit():
                stopped_reason = "limit"
                break
            try:
                youtube.videos().rate(id=video_id, rating="none").execute()
            except HttpError as exc:
                if record_error(video_id, "unlike", exc):
                    stopped_reason = "quota"
                    break
                continue
            actions += 1
            likes_done += 1
            log["unliked"].append(video_id)
            _save_log(EXECUTE_LOG_FILE, log)
            print(f"  unliked: {video_id}")

    done_subs = set(log["unsubscribed"])
    done_likes = set(log["unliked"])
    pending_unsubscribe = len([c for c in planned_subs if c not in done_subs])
    pending_unlike = len([v for v in planned_likes if v not in done_likes])
    if stopped_reason is None:
        stopped_reason = "errors" if run_errors else "completed"

    log["last_run"] = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stopped_reason": stopped_reason,
        "unsubscribed_this_run": subs_done,
        "unliked_this_run": likes_done,
        "pending_unsubscribe": pending_unsubscribe,
        "pending_unlike": pending_unlike,
        "errors": run_errors,
    }
    _save_log(EXECUTE_LOG_FILE, log)

    print(f"Done. {actions} removal(s) this run.")
    if stopped_reason == "quota":
        print(
            "Stopped: YouTube API quota exhausted for today. "
            "Re-run tomorrow to continue."
        )
    elif stopped_reason == "limit":
        print(f"Stopped at --limit {args.limit}. Re-run to continue.")
    if run_errors:
        print(
            f"{len(run_errors)} error(s) recorded in {EXECUTE_LOG_FILE} "
            "(see last_run.errors)."
        )
    if pending_unsubscribe or pending_unlike:
        print(
            f"{pending_unsubscribe} unsubscribe(s) and {pending_unlike} "
            "unlike(s) still pending."
        )
    return 0
