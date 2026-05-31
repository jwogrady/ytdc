"""Offline tests for watch-history parsing and the subs/likes join.

No network: everything runs against tiny in-repo fixtures written to tmp_path.
"""

import json

import pytest

from ytdc.errors import InputError
from ytdc.history import parse_watch_history
from ytdc.report import build_analysis

# Two channels watched, plus two entries that must be unattributable:
# one with no subtitles (an ad), one whose url is not a /channel/ link.
WATCH_HISTORY = [
    {
        "title": "Watched Alpha 1",
        "subtitles": [{"name": "Alpha", "url": "https://www.youtube.com/channel/UCalpha"}],
        "time": "2023-01-01T00:00:00Z",
    },
    {
        "title": "Watched Alpha 2",
        "subtitles": [{"name": "Alpha", "url": "https://www.youtube.com/channel/UCalpha"}],
        "time": "2023-03-01T00:00:00Z",
    },
    {
        "title": "Watched Beta 1",
        "subtitles": [{"name": "Beta", "url": "https://www.youtube.com/channel/UCbeta"}],
        "time": "2023-02-01T00:00:00Z",
    },
    {"title": "Visited an advertiser"},  # no subtitles -> unattributable
    {
        "title": "Watched a removed video",
        "subtitles": [{"name": "x", "url": "https://www.youtube.com/playlist?list=PL1"}],
        "time": "2023-04-01T00:00:00Z",
    },  # url is not a /channel/ link -> unattributable
]


def _write(path, obj):
    path.write_text(json.dumps(obj))
    return path


def test_parse_watch_history(tmp_path):
    history = _write(tmp_path / "watch-history.json", WATCH_HISTORY)
    channels, unattributable = parse_watch_history(history)

    assert unattributable == 2
    assert channels["UCalpha"]["views"] == 2
    # first/last watched track the min/max timestamps, not insertion order.
    assert channels["UCalpha"]["first_watched"] == "2023-01-01T00:00:00Z"
    assert channels["UCalpha"]["last_watched"] == "2023-03-01T00:00:00Z"
    assert channels["UCbeta"]["views"] == 1


def test_build_analysis_join(tmp_path):
    history = _write(tmp_path / "watch-history.json", WATCH_HISTORY)
    subs = _write(
        tmp_path / "subscriptions.json",
        [
            {"channel_id": "UCalpha", "title": "Alpha"},
            {"channel_id": "UCghost", "title": "Ghost"},  # subscribed, never watched
        ],
    )
    likes = _write(
        tmp_path / "likes.json",
        [{"video_id": "v1", "title": "Beta vid", "channel_id": "UCbeta", "channel_title": "Beta"}],
    )

    analysis = build_analysis(history, subscriptions_file=subs, likes_file=likes)

    by_id = {s["channel_id"]: s for s in analysis["subscriptions"]}
    assert by_id["UCalpha"]["watched"] is True
    assert by_id["UCalpha"]["views"] == 2
    assert by_id["UCghost"]["watched"] is False
    assert by_id["UCghost"]["views"] == 0
    assert by_id["UCghost"]["last_watched"] is None

    assert analysis["likes"][0]["watched"] is True
    assert analysis["likes"][0]["views"] == 1
    assert analysis["unattributable"] == 2


def test_history_non_list_raises_input_error(tmp_path):
    bad = _write(tmp_path / "wrong.json", {"not": "a list"})
    with pytest.raises(InputError):
        parse_watch_history(bad)


def test_history_invalid_json_raises_input_error(tmp_path):
    bad = tmp_path / "empty.json"
    bad.write_text("")  # not valid JSON
    with pytest.raises(InputError):
        parse_watch_history(bad)


def test_history_skips_non_dict_entries(tmp_path):
    history = _write(tmp_path / "wh.json", [42, "junk", None])
    channels, unattributable = parse_watch_history(history)
    assert channels == {}
    assert unattributable == 3


def test_join_missing_channel_id_raises_input_error(tmp_path):
    history = _write(tmp_path / "wh.json", WATCH_HISTORY)
    subs = _write(tmp_path / "subscriptions.json", [{"title": "no id here"}])
    likes = _write(tmp_path / "likes.json", [])
    with pytest.raises(InputError):
        build_analysis(history, subscriptions_file=subs, likes_file=likes)


def test_backup_not_a_list_raises_input_error(tmp_path):
    history = _write(tmp_path / "wh.json", WATCH_HISTORY)
    subs = _write(tmp_path / "subscriptions.json", {"oops": "object"})
    likes = _write(tmp_path / "likes.json", [])
    with pytest.raises(InputError):
        build_analysis(history, subscriptions_file=subs, likes_file=likes)
