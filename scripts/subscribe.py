"""One-off helper: bulk-subscribe @handles from a list file.

Dry-run by default (zero writes). Pass --execute to actually subscribe.
Reuses ytdc's cached OAuth token (scope youtube.force-ssl covers
subscriptions.insert). Skips handles already subscribed and reports any
that don't resolve.

Usage:
  uv run python scripts/subscribe.py [--list data/subscribe-list.txt]
  uv run python scripts/subscribe.py --execute
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ytdc.auth import get_credentials  # noqa: E402


def read_handles(path: Path) -> list[str]:
    handles = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        handles.append(line.lstrip("@"))
    return handles


def resolve(yt, handle: str):
    r = yt.channels().list(part="id,snippet", forHandle=handle).execute().get("items", [])
    if not r:
        return None
    return r[0]["id"], r[0]["snippet"]["title"]


def is_subscribed(yt, channel_id: str) -> bool:
    r = yt.subscriptions().list(part="id", mine=True, forChannelId=channel_id).execute()
    return bool(r.get("items"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="data/subscribe-list.txt", type=Path)
    ap.add_argument("--execute", action="store_true", help="actually subscribe (default: dry run)")
    args = ap.parse_args()

    yt = build("youtube", "v3", credentials=get_credentials())
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]
    print(f"Authorized as: {me['title']} ({me.get('customUrl', '')})\n")

    handles = read_handles(args.list)
    to_sub, already, missing = [], [], []
    for h in handles:
        res = resolve(yt, h)
        if not res:
            missing.append(h)
            print(f"  ?  @{h:<26} (handle not found)")
            continue
        cid, title = res
        if is_subscribed(yt, cid):
            already.append(title)
            print(f"  =  {title:<28} already subscribed")
        else:
            to_sub.append((cid, title))
            print(f"  +  {title:<28} will subscribe")

    print(f"\nResolved {len(handles) - len(missing)}/{len(handles)} | "
          f"new={len(to_sub)} already={len(already)} missing={len(missing)}")
    if missing:
        print(f"Missing handles (fix in {args.list}): {', '.join('@' + m for m in missing)}")

    if not args.execute:
        print("\nDRY RUN — no changes made. Pass --execute to subscribe.")
        return 0

    print("\nSubscribing...")
    ok = 0
    for cid, title in to_sub:
        try:
            yt.subscriptions().insert(
                part="snippet",
                body={"snippet": {"resourceId": {"kind": "youtube#channel", "channelId": cid}}},
            ).execute()
            print(f"  subscribed: {title}")
            ok += 1
        except HttpError as e:
            print(f"  FAILED {title}: {e}")
    print(f"\nDone. {ok}/{len(to_sub)} new subscriptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
