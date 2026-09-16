"""One-time OAuth authorization to obtain a YOUTUBE_REFRESH_TOKEN covering
both upload (Phase 5) and analytics read (Phase 6) scopes.

Run this YOURSELF, locally, on a machine with a browser (it opens one and
needs to redirect to http://localhost) - it can't be run inside a headless
sandbox/CI environment.

Prerequisites (see README's Phase 5 setup section for the full walkthrough):
  1. A Google Cloud project with the YouTube Data API v3 AND YouTube
     Analytics API both enabled.
  2. An OAuth Client ID of type "Desktop app" created in that project.
  3. YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET set in your .env.

Usage:
    ./.venv/bin/python scripts/youtube_oauth_setup.py

On success, it prints a YOUTUBE_REFRESH_TOKEN line to add to your .env.
If you already have a refresh token generated before Phase 6 (upload-only
scope), re-run this script to get a new one that also covers analytics -
the old token will keep working for uploads but will fail for analytics
calls with an insufficient-scope error.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit(
        "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env before running this script.\n"
        "See README's Phase 5 setup section for how to create them in Google Cloud Console."
    )

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.providers.youtube.scopes import ALL_SCOPES  # noqa: E402

SCOPES = ALL_SCOPES

CLIENT_CONFIG = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


def main():
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    credentials = flow.run_local_server(port=0)

    print("\nAuthorization successful. Add this line to your .env:\n")
    print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")
    print("\nThen set YOUTUBE_UPLOAD_PROVIDER=youtube to switch off the mock provider.")


if __name__ == "__main__":
    main()
