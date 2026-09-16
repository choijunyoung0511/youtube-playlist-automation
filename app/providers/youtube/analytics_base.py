"""YoutubeAnalyticsProvider abstracts *how daily performance data gets
fetched* (spec section 16), the same seam pattern as upload: a plain API
key can't read a channel's private Analytics data either, so this exists
so the collection pipeline can be built and tested with
MockYoutubeAnalyticsProvider before real OAuth credentials exist.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class DailyStats:
    date: date
    views: int
    watch_time_min: float
    average_view_duration_sec: float
    average_percentage_viewed: float
    impressions: int | None
    ctr: float | None
    likes: int
    comments: int
    subscribers_gained: int


class YoutubeAnalyticsProvider(ABC):
    name: str

    @abstractmethod
    def fetch_daily_stats(self, youtube_video_id: str, target_date: date) -> DailyStats:
        ...
