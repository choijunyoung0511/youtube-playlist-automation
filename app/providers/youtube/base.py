"""YoutubeUploadProvider abstracts *how a video actually gets published*
(spec section 15), the same way MusicGenerationProvider abstracts audio
generation. Uploading requires OAuth (a plain API key can't act on behalf
of a channel), so this interface exists specifically so the whole upload
pipeline can be built and tested with MockYoutubeUploadProvider before
any real Google Cloud OAuth credentials exist.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UploadResult:
    video_id: str
    video_url: str
    added_to_playlist: bool = False


class YoutubeUploadProvider(ABC):
    name: str

    @abstractmethod
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
        ...
