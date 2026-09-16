from __future__ import annotations

import hashlib

from .base import UploadResult, YoutubeUploadProvider


class MockYoutubeUploadProvider(YoutubeUploadProvider):
    """No network calls, no credentials needed. Generates a deterministic
    fake video ID from the inputs so the same upload request always
    produces the same ID - useful for asserting on in tests."""

    name = "mock"

    def upload_video(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: str,
        target_playlist_id: str | None = None,
    ) -> UploadResult:
        digest = hashlib.sha1(f"{video_path}|{title}".encode()).hexdigest()[:11]
        video_id = f"mock{digest}"
        return UploadResult(
            video_id=video_id,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
            added_to_playlist=bool(target_playlist_id),
        )
