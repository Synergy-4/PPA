"""
tools/google_auth.py — Shared OAuth2 helper for Google Calendar + Gmail.

Key design decisions:
- ONE combined SCOPES list covering both APIs — avoids token mismatch errors
  when the same token.json is reused across tools with different scope sets.
- Blocking file I/O and token refresh run in a thread executor so they never
  block the FastAPI async event loop.
- First run: opens a local browser window for the OAuth consent screen.
  Subsequent runs: silently refreshes the token from token.json.
"""

from __future__ import annotations

import asyncio
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Combined scopes — must cover ALL Google APIs used by any tool.
# If you add a new Google API later, add its scope here and delete token.json
# so the user re-authenticates with the expanded permissions.
# ---------------------------------------------------------------------------

GOOGLE_SCOPES = [
    # Calendar
    "https://www.googleapis.com/auth/calendar",
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]


# ---------------------------------------------------------------------------
# Sync credential loader (runs in thread executor — never call directly)
# ---------------------------------------------------------------------------

def _load_credentials_sync() -> Credentials:
    """
    Load or refresh Google OAuth2 credentials.
    Blocking — must be called via asyncio.to_thread() or run_in_executor().

    Requires token.json to already exist. Run setup_auth.py first.
    """
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"credentials.json not found at '{credentials_path}'. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    if not os.path.exists(token_path):
        raise RuntimeError(
            "token.json not found. Run this first to authenticate:\n\n"
            "    uv run python setup_auth.py\n"
        )

    creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)

    # Silent refresh if expired
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "token.json is invalid or revoked. Delete it and re-run setup_auth.py."
            )

    return creds


# ---------------------------------------------------------------------------
# Async-safe credential loader
# ---------------------------------------------------------------------------

async def get_credentials() -> Credentials:
    """
    Async-safe wrapper — runs blocking credential I/O in a thread pool
    so the FastAPI event loop is never blocked.
    """
    return await asyncio.to_thread(_load_credentials_sync)


# ---------------------------------------------------------------------------
# Async service builders
# ---------------------------------------------------------------------------

async def get_calendar_service():
    """Return an authenticated Google Calendar v3 service client."""
    creds = await get_credentials()
    # build() itself does light I/O (reads discovery doc from cache/network)
    return await asyncio.to_thread(build, "calendar", "v3", credentials=creds)


async def get_gmail_service():
    """Return an authenticated Gmail v1 service client."""
    creds = await get_credentials()
    return await asyncio.to_thread(build, "gmail", "v1", credentials=creds)