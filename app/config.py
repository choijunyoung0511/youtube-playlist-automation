from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    ai_provider: str = os.getenv("AI_PROVIDER", "mock")  # "mock" | "claude"
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    youtube_upload_provider: str = os.getenv("YOUTUBE_UPLOAD_PROVIDER", "mock")  # "mock" | "youtube"
    youtube_client_id: str | None = os.getenv("YOUTUBE_CLIENT_ID") or None
    youtube_client_secret: str | None = os.getenv("YOUTUBE_CLIENT_SECRET") or None
    youtube_refresh_token: str | None = os.getenv("YOUTUBE_REFRESH_TOKEN") or None
    youtube_default_visibility: str = os.getenv("YOUTUBE_DEFAULT_VISIBILITY", "private")  # spec section 15: PRIVATE/UNLISTED for testing
    youtube_category_id: str = os.getenv("YOUTUBE_CATEGORY_ID", "10")  # 10 = Music

    youtube_analytics_provider: str = os.getenv("YOUTUBE_ANALYTICS_PROVIDER", "mock")  # "mock" | "youtube"


settings = Settings()
