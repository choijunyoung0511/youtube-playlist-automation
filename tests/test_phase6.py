"""Pytest version of the Phase 6 flow: collect daily stats via
MockYoutubeAnalyticsProvider, verify upsert idempotency and multi-day
accumulation.
"""

import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import TrackStatus, YoutubeStats
from app.providers.mock_provider import MockAiProvider
from app.providers.youtube.mock_analytics_provider import MockYoutubeAnalyticsProvider
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider
from app.seed import ensure_default_channel
from app.services.analytics_collection_service import AnalyticsCollectionService
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
    d = Path(tempfile.mkdtemp(prefix="phase6_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_short_audio(path: Path, freq: int, duration: int = 5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _uploaded_video(db_session, tmp_dir, seed=41):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=seed)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=1)

    fixture = tmp_dir / f"track_{tracks[0].id}.wav"
    _make_short_audio(fixture, freq=220, duration=5)
    tracks[0].audio_path = str(fixture)
    tracks[0].duration_sec = 5
    tracks[0].quality_status = TrackStatus.SELECTED
    db_session.commit()

    playlist = build_and_render_playlist(
        db_session, approved,
        audio_dir=tmp_dir / "audio_out",
        video_dir=tmp_dir / "video_out",
        target_duration_sec=6,
        crossfade_sec=0,
    )
    playlist = YoutubeMetadataService(db_session, ai).generate_all(playlist, tmp_dir / "thumbnails")
    playlist = PlaylistService(db_session).approve(playlist)

    return YoutubeUploadService(db_session, MockYoutubeUploadProvider()).upload(
        playlist, privacy_status="private", category_id="10"
    ), channel


def test_collect_for_video_populates_stats(db_session, tmp_dir):
    youtube_video, _channel = _uploaded_video(db_session, tmp_dir)
    service = AnalyticsCollectionService(db_session, MockYoutubeAnalyticsProvider())

    row = service.collect_for_video(youtube_video, date.today())

    assert row.views > 0
    assert row.impressions >= row.views
    assert row.ctr is not None


def test_recollecting_same_date_upserts_not_duplicates(db_session, tmp_dir):
    youtube_video, _channel = _uploaded_video(db_session, tmp_dir, seed=42)
    service = AnalyticsCollectionService(db_session, MockYoutubeAnalyticsProvider())
    target_date = date.today()

    row1 = service.collect_for_video(youtube_video, target_date)
    row2 = service.collect_for_video(youtube_video, target_date)

    assert row1.id == row2.id
    count = db_session.query(YoutubeStats).filter(YoutubeStats.youtube_video_id == youtube_video.id).count()
    assert count == 1


def test_collect_for_channel_sweeps_all_uploaded_videos(db_session, tmp_dir):
    youtube_video, channel = _uploaded_video(db_session, tmp_dir, seed=43)
    service = AnalyticsCollectionService(db_session, MockYoutubeAnalyticsProvider())

    rows = service.collect_for_channel(channel.id, date.today() - timedelta(days=1))

    assert len(rows) == 1
    assert rows[0].youtube_video_id == youtube_video.id
