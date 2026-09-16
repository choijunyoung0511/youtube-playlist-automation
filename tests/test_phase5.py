"""Pytest version of the Phase 5 flow: upload an APPROVED playlist via
MockYoutubeUploadProvider, guard against uploading unapproved playlists.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PlaylistStatus, TrackStatus, YoutubeVideo
from app.providers.mock_provider import MockAiProvider
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider
from app.seed import ensure_default_channel
from app.services.concept_service import ConceptService
from app.services.music_prompt_service import MusicPromptService
from app.services.playlist_pipeline import build_and_render_playlist
from app.services.playlist_service import PlaylistService
from app.services.youtube_metadata_service import YoutubeMetadataService
from app.services.youtube_upload_service import YoutubeUploadService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def tmp_dir():
    d = Path(tempfile.mkdtemp(prefix="phase5_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_short_audio(path: Path, freq: int, duration: int = 5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _review_ready_playlist(db_session, tmp_dir, seed=31):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=seed)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=2)

    for i, track in enumerate(tracks):
        fixture = tmp_dir / f"track_{track.id}.wav"
        _make_short_audio(fixture, freq=220 + i * 110, duration=5)
        track.audio_path = str(fixture)
        track.duration_sec = 5
        track.quality_status = TrackStatus.SELECTED
    db_session.commit()

    playlist = build_and_render_playlist(
        db_session, approved,
        audio_dir=tmp_dir / "audio_out",
        video_dir=tmp_dir / "video_out",
        target_duration_sec=8,
        crossfade_sec=0,
    )
    playlist = YoutubeMetadataService(db_session, ai).generate_all(playlist, tmp_dir / "thumbnails")
    return playlist


def test_upload_requires_approval(db_session, tmp_dir):
    playlist = _review_ready_playlist(db_session, tmp_dir)
    service = YoutubeUploadService(db_session, MockYoutubeUploadProvider())

    with pytest.raises(ValueError, match="must be APPROVED"):
        service.upload(playlist, privacy_status="private", category_id="10")


def test_upload_records_youtube_video_and_marks_uploaded(db_session, tmp_dir):
    playlist = _review_ready_playlist(db_session, tmp_dir, seed=32)
    playlist = PlaylistService(db_session).approve(playlist)

    service = YoutubeUploadService(db_session, MockYoutubeUploadProvider())
    youtube_video = service.upload(playlist, privacy_status="private", category_id="10")

    db_session.refresh(playlist)
    assert playlist.status == PlaylistStatus.UPLOADED
    assert youtube_video.youtube_video_id.startswith("mock")
    assert youtube_video.title == playlist.chosen_title
    assert youtube_video.published_at is not None


def test_reupload_does_not_duplicate_youtube_video_row(db_session, tmp_dir):
    playlist = _review_ready_playlist(db_session, tmp_dir, seed=33)
    playlist = PlaylistService(db_session).approve(playlist)

    service = YoutubeUploadService(db_session, MockYoutubeUploadProvider())
    service.upload(playlist, privacy_status="private", category_id="10")

    playlist.status = PlaylistStatus.APPROVED
    db_session.commit()
    service.upload(playlist, privacy_status="unlisted", category_id="10")

    count = db_session.query(YoutubeVideo).filter(YoutubeVideo.playlist_id == playlist.id).count()
    assert count == 1
