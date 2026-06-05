"""Offline tests for execute: dry-run safety, resume, and the --limit gate.

A fake YouTube client stands in for the API so no network is touched and the
mutating calls can be asserted directly.
"""

import json

from ytdc import execute as ex


class _Req:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _Subscriptions:
    def __init__(self, items):
        self._items = items
        self.deleted: list[str] = []

    def list(self, **_kwargs):
        return _Req({"items": self._items})

    def list_next(self, _request, _response):
        return None

    def delete(self, id):  # noqa: A002 - mirrors the API kwarg name
        self.deleted.append(id)
        return _Req({})


class _Videos:
    def __init__(self):
        self.rated: list[tuple[str, str]] = []

    def rate(self, id, rating):  # noqa: A002 - mirrors the API kwarg name
        self.rated.append((id, rating))
        return _Req({})


class _FakeYouTube:
    def __init__(self, subscription_items):
        self._subs = _Subscriptions(subscription_items)
        self._videos = _Videos()

    def subscriptions(self):
        return self._subs

    def videos(self):
        return self._videos


def _args(plan, *, execute=False, limit=None):
    return type("Args", (), {"plan": plan, "execute": execute, "limit": limit})()


def _write_plan(tmp_path, unsubscribe, unlike):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"unsubscribe": unsubscribe, "unlike": unlike}))
    return plan


def test_dry_run_makes_no_api_calls(tmp_path, monkeypatch, capsys):
    plan = _write_plan(tmp_path, ["UCa", "UCb"], ["v1"])
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", tmp_path / "log.json")

    def boom(*_a, **_k):
        raise AssertionError("dry-run must not build the API service")

    monkeypatch.setattr(ex, "build_youtube_service", boom)

    assert ex.cmd_execute(_args(plan)) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "UCa" in out and "UCb" in out and "v1" in out
    assert not (tmp_path / "log.json").exists()  # dry-run writes no log


def test_resume_filters_already_done(tmp_path, monkeypatch, capsys):
    plan = _write_plan(tmp_path, ["UCa", "UCb"], ["v1", "v2"])
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"unsubscribed": ["UCa"], "unliked": ["v1"]}))
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)

    ex.cmd_execute(_args(plan))
    out = capsys.readouterr().out
    assert "Would unsubscribe from 1 channel" in out
    assert "Would unlike 1 video" in out
    assert "UCb" in out and "v2" in out
    assert "UCa" not in out and "v1" not in out  # already done -> filtered out


def test_execute_deletes_rates_and_honors_limit(tmp_path, monkeypatch, capsys):
    plan = _write_plan(tmp_path, ["UCa", "UCb"], ["v1", "v2"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube(
        [
            {"id": "sub-a", "snippet": {"resourceId": {"channelId": "UCa"}}},
            {"id": "sub-b", "snippet": {"resourceId": {"channelId": "UCb"}}},
        ]
    )
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    # limit 3 -> 2 unsubscribes + 1 unlike; v2 deferred to a later run.
    ex.cmd_execute(_args(plan, execute=True, limit=3))

    assert fake._subs.deleted == ["sub-a", "sub-b"]
    assert fake._videos.rated == [("v1", "none")]
    saved = json.loads(log.read_text())
    assert saved["unsubscribed"] == ["UCa", "UCb"]
    assert saved["unliked"] == ["v1"]
    assert "Stopped at --limit 3" in capsys.readouterr().out


def test_execute_continues_past_api_error(tmp_path, monkeypatch):
    import httplib2
    from googleapiclient.errors import HttpError

    plan = _write_plan(tmp_path, [], ["v1", "v2"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    calls: list[str] = []

    def rate(id, rating):  # noqa: A002 - mirrors the API kwarg name
        calls.append(id)
        if id == "v1":
            raise HttpError(httplib2.Response({"status": 403}), b"quota")
        return _Req({})

    fake._videos.rate = rate
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    assert calls == ["v1", "v2"]  # one failure did not abort the run
    # v1 failed -> not logged (retried next time); v2 succeeded -> logged.
    assert json.loads(log.read_text())["unliked"] == ["v2"]


def test_execute_dedupes_plan(tmp_path, monkeypatch):
    plan = _write_plan(tmp_path, [], ["v1", "v1"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    assert fake._videos.rated == [("v1", "none")]  # rated once, not twice


def _http_error(status, reason=None, message="boom"):
    import httplib2
    from googleapiclient.errors import HttpError

    body = {"error": {"message": message}}
    if reason is not None:
        body["error"]["errors"] = [{"reason": reason}]
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


def test_last_run_recorded_on_full_run(tmp_path, monkeypatch):
    plan = _write_plan(tmp_path, [], ["v1", "v2"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    last = json.loads(log.read_text())["last_run"]
    assert last["stopped_reason"] == "completed"
    assert last["unliked_this_run"] == 2
    assert last["pending_unlike"] == 0
    assert last["errors"] == []
    assert last["finished_at"]  # timestamp present


def test_quota_error_short_circuits_and_is_recorded(tmp_path, monkeypatch, capsys):
    plan = _write_plan(tmp_path, [], ["v1", "v2", "v3"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    calls: list[str] = []

    def rate(id, rating):  # noqa: A002 - mirrors the API kwarg name
        calls.append(id)
        if id == "v2":
            raise _http_error(403, reason="quotaExceeded", message="quota gone")
        return _Req({})

    fake._videos.rate = rate
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    assert calls == ["v1", "v2"]  # v3 never attempted — quota stop short-circuits
    saved = json.loads(log.read_text())
    assert saved["unliked"] == ["v1"]  # v2 failed, not logged
    last = saved["last_run"]
    assert last["stopped_reason"] == "quota"
    assert last["pending_unlike"] == 2  # v2 + v3 remain
    assert last["errors"][0] == {
        "id": "v2",
        "action": "unlike",
        "status": 403,
        "reason": "quotaExceeded",
        "message": "quota gone",
    }
    assert "quota exhausted" in capsys.readouterr().out


def test_non_quota_error_continues_and_records(tmp_path, monkeypatch):
    plan = _write_plan(tmp_path, [], ["v1", "v2"])
    log = tmp_path / "log.json"
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    calls: list[str] = []

    def rate(id, rating):  # noqa: A002 - mirrors the API kwarg name
        calls.append(id)
        if id == "v1":
            raise _http_error(404, reason="videoNotFound", message="gone")
        return _Req({})

    fake._videos.rate = rate
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    assert calls == ["v1", "v2"]  # transient/other errors don't stop the run
    last = json.loads(log.read_text())["last_run"]
    assert last["stopped_reason"] == "errors"
    assert last["errors"][0]["reason"] == "videoNotFound"


def test_dry_run_reports_last_run_summary(tmp_path, monkeypatch, capsys):
    plan = _write_plan(tmp_path, [], ["v1"])
    log = tmp_path / "log.json"
    log.write_text(
        json.dumps(
            {
                "unsubscribed": [],
                "unliked": [],
                "last_run": {
                    "finished_at": "2026-06-02T10:05:00+00:00",
                    "stopped_reason": "quota",
                    "unsubscribed_this_run": 468,
                    "unliked_this_run": 0,
                    "pending_unsubscribe": 374,
                    "pending_unlike": 0,
                    "errors": [{"id": "UCx", "action": "unsubscribe"}],
                },
            }
        )
    )
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)

    ex.cmd_execute(_args(plan))  # dry-run

    out = capsys.readouterr().out
    assert "Last execute run (2026-06-02T10:05:00+00:00)" in out
    assert "468 unsubscribed" in out
    assert "stopped=quota" in out
    assert "1 error(s)" in out


def test_execute_resumes_remaining_after_limit(tmp_path, monkeypatch):
    plan = _write_plan(tmp_path, [], ["v1", "v2"])
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"unsubscribed": [], "unliked": ["v1"]}))
    monkeypatch.setattr(ex, "EXECUTE_LOG_FILE", log)
    fake = _FakeYouTube([])
    monkeypatch.setattr(ex, "build_youtube_service", lambda *_a, **_k: fake)

    ex.cmd_execute(_args(plan, execute=True))

    assert fake._videos.rated == [("v2", "none")]  # only the un-done one
    assert json.loads(log.read_text())["unliked"] == ["v1", "v2"]
