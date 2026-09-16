from ...config import settings
from .analytics_base import YoutubeAnalyticsProvider
from .mock_analytics_provider import MockYoutubeAnalyticsProvider
from .real_analytics_provider import RealYoutubeAnalyticsProvider


def get_youtube_analytics_provider() -> YoutubeAnalyticsProvider:
    if settings.youtube_analytics_provider == "youtube":
        return RealYoutubeAnalyticsProvider(
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            refresh_token=settings.youtube_refresh_token,
        )
    return MockYoutubeAnalyticsProvider()
