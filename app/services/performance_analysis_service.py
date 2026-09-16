"""Joins accumulated YoutubeStats with the Concept/Track/Playlist metadata
that produced each video, and scores them so the strongest performers can
be identified (spec section 17: consider views, CTR, retention, watch
time, subscriber conversion, and comments together - not views alone).
"""

from sqlalchemy.orm import Session

from ..models import Concept, Playlist, YoutubeVideo
from ..providers.types import VideoPerformanceRecord


class PerformanceAnalysisService:
    def __init__(self, db: Session):
        self.db = db

    def build_records(self, channel_id: int) -> list[VideoPerformanceRecord]:
        videos = (
            self.db.query(YoutubeVideo)
            .join(Playlist, YoutubeVideo.playlist_id == Playlist.id)
            .join(Concept, Playlist.concept_id == Concept.id)
            .filter(Concept.channel_id == channel_id, YoutubeVideo.youtube_video_id.isnot(None))
            .all()
        )

        records: list[VideoPerformanceRecord] = []
        for video in videos:
            stats = video.stats
            if not stats:
                continue  # uploaded but no analytics collected yet - nothing to learn from

            playlist = video.playlist
            concept = playlist.concept
            bpm_values = sorted({link.track.bpm for link in playlist.track_links if link.track.bpm})

            days = len(stats)
            total_views = sum(s.views or 0 for s in stats)
            total_watch_time = sum(s.watch_time_min or 0 for s in stats)
            total_likes = sum(s.likes or 0 for s in stats)
            total_comments = sum(s.comments or 0 for s in stats)
            total_subs = sum(s.subscribers_gained or 0 for s in stats)
            avg_view_dur = sum(s.average_view_duration_sec or 0 for s in stats) / days
            avg_pct_viewed = sum(s.average_percentage_viewed or 0 for s in stats) / days
            ctr_values = [s.ctr for s in stats if s.ctr is not None]
            avg_ctr = sum(ctr_values) / len(ctr_values) if ctr_values else 0.0

            record = VideoPerformanceRecord(
                playlist_id=playlist.id,
                concept_name=concept.concept_name,
                listening_situation=concept.listening_situation,
                genre=concept.genre,
                sub_genre=concept.sub_genre,
                mood=concept.mood,
                target_audience=concept.target_audience,
                bpm_values=bpm_values,
                video_length_min=round((playlist.duration_sec or 0) / 60, 1),
                chosen_title=playlist.chosen_title or playlist.title,
                thumbnail_text=playlist.thumbnail_text,
                total_views=total_views,
                total_watch_time_min=round(total_watch_time, 1),
                avg_view_duration_sec=round(avg_view_dur, 1),
                avg_percentage_viewed=round(avg_pct_viewed, 1),
                avg_ctr=round(avg_ctr, 2),
                total_likes=total_likes,
                total_comments=total_comments,
                total_subscribers_gained=total_subs,
                days_tracked=days,
            )
            record.score = self._score(record)
            records.append(record)

        records.sort(key=lambda r: r.score, reverse=True)
        return records

    @staticmethod
    def _score(r: VideoPerformanceRecord) -> float:
        """Deliberately simple weighted heuristic, not a normalized/z-scored
        model - fine for ranking a channel's own small set of videos
        against each other, which is all Phase 7 needs."""
        view_score = min(r.total_views / 10, 100)
        ctr_score = r.avg_ctr
        retention_score = r.avg_percentage_viewed
        sub_conversion = (r.total_subscribers_gained / r.total_views * 1000) if r.total_views else 0
        comment_rate = (r.total_comments / r.total_views * 1000) if r.total_views else 0
        return round(
            view_score * 0.25
            + ctr_score * 0.25
            + retention_score * 0.30
            + sub_conversion * 0.10
            + comment_rate * 0.10,
            2,
        )
