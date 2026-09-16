from dataclasses import asdict

from sqlalchemy.orm import Session

from ..models import Track, TrackStatus
from .audio_analysis_service import analyze_audio


class TrackQualityService:
    """Runs objective audio analysis on an uploaded Track and moves it
    through GENERATED -> ANALYZING -> SELECTED/REJECTED (spec section 8-9)."""

    def __init__(self, db: Session):
        self.db = db

    def evaluate(self, track: Track) -> Track:
        if not track.audio_path:
            raise ValueError(f"Track {track.id} has no audio_path to analyze")

        track.quality_status = TrackStatus.ANALYZING
        self.db.commit()

        target_duration = (track.prompt or {}).get("duration_target_sec")
        result = analyze_audio(track.audio_path, target_duration_sec=target_duration)

        track.analysis_data = asdict(result)
        track.duration_sec = int(result.duration_sec)

        if result.passed:
            track.quality_status = TrackStatus.SELECTED
            track.quality_reason = "모든 오디오 품질 기준 통과"
        else:
            track.quality_status = TrackStatus.REJECTED
            track.quality_reason = "; ".join(result.issues)

        self.db.commit()
        self.db.refresh(track)
        return track
