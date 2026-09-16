"""Uploads an APPROVED Playlist to YouTube (spec section 15) and records
the result. Never auto-uploads anything - callers are responsible for
only invoking this once a human has approved the Playlist."""

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Playlist, PlaylistStatus, YoutubeVideo
from ..providers.youtube.base import YoutubeUploadProvider


class YoutubeUploadService:
    def __init__(self, db: Session, provider: YoutubeUploadProvider):
        self.db = db
        self.provider = provider

    def upload(self, playlist: Playlist, privacy_status: str, category_id: str) -> YoutubeVideo:
        if playlist.status != PlaylistStatus.APPROVED:
            raise ValueError(
                f"Playlist {playlist.id} must be APPROVED before upload (current status: {playlist.status.value})"
            )
        if not playlist.video_path:
            raise ValueError(f"Playlist {playlist.id} has no rendered video to upload")

        title = playlist.chosen_title or playlist.title
        target_playlist_id = playlist.concept.channel.youtube_playlist_id

        result = self.provider.upload_video(
            video_path=playlist.video_path,
            thumbnail_path=playlist.thumbnail_path,
            title=title,
            description=playlist.youtube_description or "",
            tags=playlist.keywords or [],
            category_id=category_id,
            privacy_status=privacy_status,
            target_playlist_id=target_playlist_id,
        )

        youtube_video = self.db.query(YoutubeVideo).filter(YoutubeVideo.playlist_id == playlist.id).first()
        if youtube_video is None:
            youtube_video = YoutubeVideo(playlist_id=playlist.id)
            self.db.add(youtube_video)

        youtube_video.youtube_video_id = result.video_id
        youtube_video.title = title
        youtube_video.published_at = datetime.utcnow()

        playlist.status = PlaylistStatus.UPLOADED
        self.db.commit()
        self.db.refresh(youtube_video)
        return youtube_video
