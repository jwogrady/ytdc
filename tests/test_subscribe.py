"""Offline tests for subscribe: dry-run safety, idempotent skip, resolution.

A fake YouTube client stands in for the API so no network is touched and the
subscriptions.insert calls can be asserted directly.
"""

from ytdc import subscribe as sub


class _Req:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _Channels:
    def __init__(self, by_handle):
        self._by_handle = by_handle  # handle -> (channel_id, title)

    def list(self, part, forHandle):  # noqa: A002 - mirrors the API kwarg name
        hit = self._by_handle.get(forHandle)
        items = [] if hit is None else [{"id": hit[0], "snippet": {"title": hit[1]}}]
        return _Req({"items": items})


class _Subscriptions:
    def __init__(self, existing_channel_ids):
        self._items = [
            {"snippet": {"resourceId": {"channelId": cid}}}
            for cid in existing_channel_ids
        ]
        self.inserted: list[str] = []

    def list(self, **_kwargs):
        return _Req({"items": self._items})

    def list_next(self, _request, _response):
        return None

    def insert(self, part, body):  # noqa: A002 - mirrors the API kwarg name
        self.inserted.append(body["snippet"]["resourceId"]["channelId"])
        return _Req({})


class _FakeYouTube:
    def __init__(self, by_handle, existing):
        self._channels = _Channels(by_handle)
        self._subs = _Subscriptions(existing)

    def channels(self):
        return self._channels

    def subscriptions(self):
        return self._subs


def _args(list_path, *, execute=False):
    return type("Args", (), {"list": list_path, "execute": execute})()


def _write_list(tmp_path, lines):
    path = tmp_path / "subscribe-list.txt"
    path.write_text("\n".join(lines))
    return path


def test_dry_run_makes_no_api_calls(tmp_path, monkeypatch, capsys):
    list_path = _write_list(tmp_path, ["# comment", "", "@AndrejKarpathy", "Fireship"])

    def boom(*_a, **_k):
        raise AssertionError("dry-run must not build the API service")

    monkeypatch.setattr(sub, "build_youtube_service", boom)

    assert sub.cmd_subscribe(_args(list_path)) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "@AndrejKarpathy" in out and "@Fireship" in out


def test_subscribes_only_missing(tmp_path, monkeypatch, capsys):
    list_path = _write_list(tmp_path, ["@new1", "@have", "@new2"])
    fake = _FakeYouTube(
        by_handle={
            "new1": ("UCnew1", "New One"),
            "have": ("UChave", "Have"),
            "new2": ("UCnew2", "New Two"),
        },
        existing={"UChave"},
    )
    monkeypatch.setattr(sub, "build_youtube_service", lambda: fake)

    assert sub.cmd_subscribe(_args(list_path, execute=True)) == 0
    assert fake._subs.inserted == ["UCnew1", "UCnew2"]
    out = capsys.readouterr().out
    assert "Have: already subscribed" in out
    assert "Done. 2 new, 1 already subscribed, 0 unresolved, 0 error(s)." in out


def test_reports_unresolved_handles(tmp_path, monkeypatch, capsys):
    list_path = _write_list(tmp_path, ["@good", "@bogus"])
    fake = _FakeYouTube(by_handle={"good": ("UCgood", "Good")}, existing=set())
    monkeypatch.setattr(sub, "build_youtube_service", lambda: fake)

    assert sub.cmd_subscribe(_args(list_path, execute=True)) == 0
    assert fake._subs.inserted == ["UCgood"]
    captured = capsys.readouterr()
    assert "@bogus" in captured.err
    assert "Unresolved handles: @bogus" in captured.out


def test_duplicate_handle_is_deduped(tmp_path):
    list_path = _write_list(tmp_path, ["@a", "a", "@b", "# a", "@a"])
    assert sub.read_handles(list_path) == ["a", "b"]


def test_missing_list_file_raises(tmp_path):
    try:
        sub.read_handles(tmp_path / "nope.txt")
    except FileNotFoundError as exc:
        assert "nope.txt" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for a missing list")
