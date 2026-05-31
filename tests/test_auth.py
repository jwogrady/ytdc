"""Offline tests for credential-cache handling (permissions + bad-cache)."""

import json

from ytdc import auth


class _FakeCreds:
    def to_json(self):
        return json.dumps({"token": "x", "refresh_token": "y"})


def test_save_token_is_owner_only(tmp_path):
    token_file = tmp_path / "sub" / "token.json"
    auth._save_token(token_file, _FakeCreds())
    assert oct(token_file.stat().st_mode & 0o777) == "0o600"
    assert oct(token_file.parent.stat().st_mode & 0o777) == "0o700"


def test_save_token_tightens_preexisting_loose_file(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("stale")
    token_file.chmod(0o644)
    auth._save_token(token_file, _FakeCreds())
    assert oct(token_file.stat().st_mode & 0o777) == "0o600"


def test_load_cached_token_missing_returns_none(tmp_path):
    assert auth._load_cached_token(tmp_path / "nope.json") is None


def test_load_cached_token_corrupt_returns_none(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("not json{")
    assert auth._load_cached_token(token_file) is None


def test_load_cached_token_missing_fields_returns_none(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")  # valid JSON, missing required fields
    assert auth._load_cached_token(token_file) is None
