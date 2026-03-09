"""
setup_auth.py — One-time Google OAuth2 authentication script.

Run this ONCE before starting the server:
    uv run python setup_auth.py

What it does:
  1. Opens your browser to Google's OAuth consent page
  2. You log in and click Allow
  3. Writes token.json to this directory
  4. The server reads token.json on every subsequent request (no browser needed)

Re-run this script if:
  - You delete token.json
  - Your token gets revoked
  - You see auth errors in the server
"""

import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")

if not os.path.exists(credentials_path):
    print(f"\n❌  credentials.json not found at '{credentials_path}'")
    print("    Download it from Google Cloud Console → APIs & Services → Credentials")
    print("    and save it as credentials.json in this directory.\n")
    exit(1)

print("\n🔐  Starting Google OAuth flow...")
print("    A browser window will open. Log in and click Allow.\n")

flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GOOGLE_SCOPES)
creds = flow.run_local_server(port=0)

with open(token_path, "w") as f:
    f.write(creds.to_json())

print(f"\n✅  Authentication successful! token.json saved to '{token_path}'")
print("    You can now start the server:\n")
print("    uv run uvicorn main:app --reload --port 8000\n")