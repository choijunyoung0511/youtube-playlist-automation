import hashlib
from datetime import date

from .analytics_base import DailyStats, YoutubeAnalyticsProvider


class MockYoutubeAnalyticsProvider(YoutubeAnalyticsProvider):
    """No network calls. Deterministic per (video_id, date) so re-running
    collection for the same day in tests always yields the same numbers,
    while still varying across dates/videos to look like real data."""

    name = "mock"

    def fetch_daily_stats(self, youtube_video_id: str, target_date: date) -> DailyStats:
        seed = int(hashlib.sha1(f"{youtube_video_id}|{target_date.isoformat()}".encode()).hexdigest()[:8], 16)

        views = 40 + seed % 400
        watch_time_min = round(views * (2.5 + (seed % 100) / 40), 1)
        average_view_duration_sec = round((watch_time_min * 60) / max(views, 1), 1)
        average_percentage_viewed = round(35 + (seed % 50), 1)
        impressions = views * (6 + seed % 10)
        ctr = round((views / impressions) * 100, 2) if impressions else None
        likes = seed % (views // 5 + 1) if views else 0
        comments = seed % (views // 20 + 1) if views else 0
        subscribers_gained = seed % 5

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
