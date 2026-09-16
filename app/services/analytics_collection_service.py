"""Collects and upserts daily performance stats for uploaded videos (spec
section 16). Idempotent: re-running for the same (video, date) updates the
existing YoutubeStats row via the unique constraint on the model, rather
than accumulating duplicates."""

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import Channel, Concept, Playlist, YoutubeStats, YoutubeVideo
from ..providers.youtube.analytics_base import YoutubeAnalyticsProvider


class AnalyticsCollectionService:
    def __init__(self, db: Session, provider: YoutubeAnalyticsProvider):
        self.db = db
        self.provider = provider

    def collect_for_video(self, youtube_video: YoutubeVideo, target_date: date) -> YoutubeStats:
        stats_data = self.provider.fetch_daily_stats(youtube_video.youtube_video_id, target_date)
        target_datetime = datetime.combine(target_date, datetime.min.time())

        row = (
            self.db.query(YoutubeStats)
            .filter(YoutubeStats.youtube_video_id == youtube_video.id, YoutubeStats.date == target_datetime)
            .first()
        )
        if row is None:
            row = YoutubeStats(youtube_video_id=youtube_video.id, date=target_datetime)
            self.db.add(row)

        row.views = stats_data.views
        row.watch_time_min = stats_data.watch_time_min
        row.average_view_duration_sec = stats_data.average_view_duration_sec
        row.average_percentage_viewed = stats_data.average_percentage_viewed
        row.impressions = stats_data.impressions
        row.ctr = stats_data.ctr
        row.likes = stats_data.likes
        row.comments = stats_data.comments
        row.subscribers_gained = stats_data.subscribers_gained

        self.db.commit()
        self.db.refresh(row)
        return row

    def collect_for_channel(self, channel_id: int, target_date: date) -> list[YoutubeStats]:
        videos = (
            self.db.query(YoutubeVideo)
            .join(Playlist, YoutubeVideo.playlist_id == Playlist.id)
            .join(Concept, Playlist.concept_id == Concept.id)
            .filter(Concept.channel_id == channel_id, YoutubeVideo.youtube_video_id.isnot(None))
            .all()
        )
        return [self.collect_for_video(v, target_date) for v in videos]

    def collect_for_all_channels(self, target_date: date) -> list[YoutubeStats]:
        results = []
        for (channel_id,) in self.db.query(Channel.id).all():
            results.extend(self.collect_for_channel(channel_id, target_date))
        return results
