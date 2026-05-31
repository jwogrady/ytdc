"""OAuth authentication for the YouTube Data API.

Runs Google's installed-app OAuth flow once and caches the resulting token so
later commands can reuse it without prompting again.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# Removing subscriptions and clearing likes both require the force-ssl scope.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

CLIENT_SECRET_FILE = Path("client_secret.json")
TOKEN_FILE = Path("data/token.json")


class AuthError(Exception):
    """Raised when usable credentials are unavailable for a non-interactive command."""


def get_credentials(
    client_secret_file: Path = CLIENT_SECRET_FILE,
    token_file: Path = TOKEN_FILE,
) -> Credentials:
    """Return valid OAuth credentials, running the consent flow if needed.

    Reuses the cached token at ``token_file`` when present, refreshing it
    silently when expired. Falls back to the interactive installed-app flow
    only when there is no usable cached token.
    """
    creds = _load_cached_token(token_file)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # Revoked or otherwise unusable refresh token: re-authenticate.
            creds = _run_consent_flow(client_secret_file)
    else:
        creds = _run_consent_flow(client_secret_file)

    _save_token(token_file, creds)
    return creds


def _load_cached_token(token_file: Path) -> Credentials | None:
    """Load cached credentials, treating a corrupt cache as absent."""
    if not token_file.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(token_file), SCOPES)
    except (ValueError, OSError):
        # Malformed (bad JSON / missing fields) or unreadable cache: re-authenticate.
        return None


def _run_consent_flow(client_secret_file: Path) -> Credentials:
    """Run the interactive installed-app OAuth flow."""
    if not client_secret_file.exists():
        raise FileNotFoundError(
            f"Missing {client_secret_file}. Download a Desktop OAuth client "
            "from the Google Cloud Console and save it there (see README)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
    return flow.run_local_server(port=0)


def _save_token(token_file: Path, creds: Credentials) -> None:
    """Persist credentials with owner-only permissions (token is a secret)."""
    token_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Create at 0600 from the start so there is no world-readable window between
    # writing and chmod; chmod too, in case the file already existed looser.
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(creds.to_json())
    token_file.chmod(0o600)


def load_existing_credentials(token_file: Path = TOKEN_FILE) -> Credentials:
    """Return cached credentials without launching the consent flow.

    For non-interactive commands (fetch, execute) that must not pop a browser.
    Raises :class:`AuthError` when the user has not run ``ytdc auth`` yet, or
    the cached token is unusable and cannot be refreshed.
    """
    creds = _load_cached_token(token_file)
    if creds is None:
        raise AuthError(
            f"Not authenticated: {token_file} is missing or invalid. "
            "Run `ytdc auth` first."
        )
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise AuthError(
                "Cached credentials expired and could not be refreshed. "
                "Run `ytdc auth` again."
            ) from exc
        _save_token(token_file, creds)
        return creds
    raise AuthError(
        f"Cached credentials at {token_file} are unusable. Run `ytdc auth` again."
    )


def build_youtube_service(creds: Credentials | None = None):
    """Build an authenticated YouTube Data API v3 client.

    Loads cached credentials when none are supplied.
    """
    if creds is None:
        creds = load_existing_credentials()
    return build("youtube", "v3", credentials=creds)


def cmd_auth(args: argparse.Namespace) -> int:
    """CLI handler for ``ytdc auth``."""
    get_credentials()
    print(f"Authenticated. Token cached at {TOKEN_FILE}.")
    return 0
