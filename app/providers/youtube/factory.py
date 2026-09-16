from ...config import settings
from .base import YoutubeUploadProvider
from .mock_provider import MockYoutubeUploadProvider
from .real_provider import RealYoutubeUploadProvider


def get_youtube_upload_provider() -> YoutubeUploadProvider:
    if settings.youtube_upload_provider == "youtube":
        return RealYoutubeUploadProvider(
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            refresh_token=settings.youtube_refresh_token,
        )
    return MockYoutubeUploadProvider()
