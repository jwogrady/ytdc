"""Join subscriptions and likes against watch history into an annotated report.

``analyze`` makes no API calls: it reads the existing ``fetch-subs`` /
``fetch-likes`` backups and a Takeout history file, then annotates each
subscribed channel and each liked video with its watch stats so a keep /
unsubscribe / unlike plan can be judged from real data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ytdc.errors import InputError
from ytdc.history import parse_watch_history
from ytdc.likes import LIKES_FILE
from ytdc.subs import SUBSCRIPTIONS_FILE

ANALYSIS_FILE = Path("data/analysis.json")


def _read_json_list(path: Path) -> list[dict]:
    """Read a JSON array from a backup file, with clear errors on bad input."""
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run the matching fetch command first.")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise InputError(f"{path} should contain a JSON array.")
    return data


def _annotate(record: dict, channels: dict[str, dict], source: Path) -> dict:
    """Attach watch stats (or zeroed defaults) to a subscription or like."""
    if not isinstance(record, dict) or "channel_id" not in record:
        raise InputError(f"{source} contains a record without a 'channel_id'.")
    stat = channels.get(record["channel_id"])
    return {
        **record,
        "views": stat["views"] if stat else 0,
        "first_watched": stat["first_watched"] if stat else None,
        "last_watched": stat["last_watched"] if stat else None,
        "watched": stat is not None,
    }


def build_analysis(
    history_path: Path,
    subscriptions_file: Path = SUBSCRIPTIONS_FILE,
    likes_file: Path = LIKES_FILE,
) -> dict:
    """Build the annotated analysis joining backups against watch history."""
    channels, unattributable = parse_watch_history(history_path)
    subs = _read_json_list(subscriptions_file)
    likes = _read_json_list(likes_file)

    return {
        "subscriptions": [_annotate(s, channels, subscriptions_file) for s in subs],
        "likes": [_annotate(lk, channels, likes_file) for lk in likes],
        "unattributable": unattributable,
    }


def cmd_analyze(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc analyze --history <path>``."""
    if not args.history.exists():
        raise FileNotFoundError(f"History file not found: {args.history}")
    analysis = build_analysis(args.history)
    ANALYSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2))
    print(
        f"Analyzed {len(analysis['subscriptions'])} subscriptions, "
        f"{len(analysis['likes'])} likes "
        f"({analysis['unattributable']} unattributable history entries) "
        f"→ {ANALYSIS_FILE}"
    )
    return 0
