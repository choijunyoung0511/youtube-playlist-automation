"""Real YouTube Analytics API v2 daily stats fetch via OAuth 2.0.

Not used by default (YOUTUBE_ANALYTICS_PROVIDER=mock). Like
RealYoutubeUploadProvider, credentials are only required the moment
fetch_daily_stats() actually runs. Uses the same refresh token as upload
(scripts/youtube_oauth_setup.py requests both scopes together).

Impressions/CTR can't be combined with the engagement metrics
(views/watchTime/etc.) in a single YouTube Analytics API query, so this
issues two queries per call and merges them. Either can come back empty
(e.g. the video is too new, or the date is outside its available data
range) - that's treated as zero/None, not an error.
"""

from datetime import date

from .analytics_base import DailyStats, YoutubeAnalyticsProvider
from .scopes import ALL_SCOPES

ENGAGEMENT_METRICS = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained"
IMPRESSION_METRICS = "impressions,impressionsClickThroughRate"


class RealYoutubeAnalyticsProvider(YoutubeAnalyticsProvider):
    name = "youtube"

    def __init__(self, client_id: str | None, client_secret: str | None, refresh_token: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._client = None

    def _get_client(self):
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise RuntimeError(
                "RealYoutubeAnalyticsProvider requires YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
                "and YOUTUBE_REFRESH_TOKEN (with analytics scope). Run scripts/youtube_oauth_setup.py, "
                "or set YOUTUBE_ANALYTICS_PROVIDER=mock to test without real credentials."
            )
        if self._client is None:
            from google.oauth2.credentials import Credentials  # lazy: not a hard dependency for mock-only runs
            from googleapiclient.discovery import build

            credentials = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=ALL_SCOPES,
            )
            self._client = build("youtubeAnalytics", "v2", credentials=credentials)
        return self._client

    def fetch_daily_stats(self, youtube_video_id: str, target_date: date) -> DailyStats:
        client = self._get_client()
        date_str = target_date.isoformat()

        engagement_row = self._query_row(client, date_str, youtube_video_id, ENGAGEMENT_METRICS)
        impression_row = self._query_row(client, date_str, youtube_video_id, IMPRESSION_METRICS)

        views = int(engagement_row[0]) if engagement_row else 0
        watch_time_min = float(engagement_row[1]) if engagement_row else 0.0
        average_view_duration_sec = float(engagement_row[2]) if engagement_row else 0.0
        average_percentage_viewed = float(engagement_row[3]) if engagement_row else 0.0
        likes = int(engagement_row[4]) if engagement_row else 0
        comments = int(engagement_row[5]) if engagement_row else 0
        subscribers_gained = int(engagement_row[6]) if engagement_row else 0

        impressions = int(impression_row[0]) if impression_row else None
        ctr = float(impression_row[1]) if impression_row else None

        return DailyStats(
            date=target_date,
            views=views,
            watch_time_min=watch_time_min,
            average_view_duration_sec=average_view_duration_sec,
            average_percentage_viewed=average_percentage_viewed,
            impressions=impressions,
            ctr=ctr,
            likes=likes,
            comments=comments,
            subscribers_gained=subscribers_gained,
        )

    def _query_row(self, client, date_str: str, youtube_video_id: str, metrics: str) -> list | None:
        response = client.reports().query(
            ids="channel==MINE",
            startDate=date_str,
            endDate=date_str,
            metrics=metrics,
            dimensions="video",
            filters=f"video=={youtube_video_id}",
        ).execute()
        rows = response.get("rows") or []
        if not rows:
            return None
        return rows[0][1:]  # first column is the video ID dimension, drop it
