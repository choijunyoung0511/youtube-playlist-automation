"""Pytest version of the Phase 7 flow: performance-based ranking, strategy
extraction favoring the winner (not the loser), and biased-but-varied
next concept batch.
"""

import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import TrackStatus, YoutubeStats
from app.providers.mock_provider import MockAiProvider
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider
from app.seed import ensure_default_channel
from app.services.concept_service import ConceptService
from app.services.content_strategy_service import ContentStrategyService
from app.services.music_prompt_service import MusicPromptService
from app.services.performance_analysis_service import PerformanceAnalysisService
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
    d = Path(tempfile.mkdtemp(prefix="phase7_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_short_audio(path: Path, freq: int, duration: int = 5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _upload(db_session, ai, music_service, concept, tmp_dir, freq, label):
    tracks = music_service.generate_tracks(concept, count=1)
    fixture = tmp_dir / f"track_{tracks[0].id}.wav"
    _make_short_audio(fixture, freq=freq, duration=5)
    tracks[0].audio_path = str(fixture)
    tracks[0].duration_sec = 5
    tracks[0].bpm = 80
    tracks[0].quality_status = TrackStatus.SELECTED
    db_session.commit()

    playlist = build_and_render_playlist(
        db_session, concept,
        audio_dir=tmp_dir / f"audio_{label}",
        video_dir=tmp_dir / f"video_{label}",
        target_duration_sec=5,
        crossfade_sec=0,
    )
    playlist = YoutubeMetadataService(db_session, ai).generate_all(playlist, tmp_dir / "thumbnails")
    playlist = PlaylistService(db_session).approve(playlist)
    return playlist, YoutubeUploadService(db_session, MockYoutubeUploadProvider()).upload(
        playlist, privacy_status="private", category_id="10"
    )


def _write_stats(db_session, youtube_video, views, ctr, pct_viewed, subs):
    for i in range(2):
        db_session.add(YoutubeStats(
            youtube_video_id=youtube_video.id,
            date=datetime.utcnow() - timedelta(days=i),
            views=views, watch_time_min=views * 3.0, average_view_duration_sec=180.0,
            average_percentage_viewed=pct_viewed, impressions=views * 8, ctr=ctr,
            likes=views // 10, comments=views // 20, subscribers_gained=subs,
        ))
    db_session.commit()


def test_strategy_favors_winner_and_biases_next_batch(db_session, tmp_dir):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=27)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    winner = concept_service.approve(top3[0].id)
    loser = concept_service.approve(top3[1].id)

    winner_playlist, winner_video = _upload(db_session, ai, music_service, winner, tmp_dir, 220, "winner")
    loser_playlist, loser_video = _upload(db_session, ai, music_service, loser, tmp_dir, 440, "loser")

    _write_stats(db_session, winner_video, views=5000, ctr=9.5, pct_viewed=78.0, subs=40)
    _write_stats(db_session, loser_video, views=80, ctr=1.2, pct_viewed=15.0, subs=0)

    records = PerformanceAnalysisService(db_session).build_records(channel.id)
    assert records[0].playlist_id == winner_playlist.id
    assert records[0].score > records[1].score

    strategy = ContentStrategyService(db_session, ai).refresh_strategy(channel)
    assert strategy is not None
    assert winner.genre in strategy.recommended_genres

    next_batch = concept_service.generate_and_evaluate(channel, count=10)
    biased = [c for c in next_batch if c.genre in strategy.recommended_genres or c.mood in strategy.recommended_moods]

    assert 0 < len(biased) < len(next_batch)
    assert all(c.concept_name != winner.concept_name for c in next_batch)


def test_no_strategy_without_uploaded_video_stats(db_session):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=28)

    strategy = ContentStrategyService(db_session, ai).refresh_strategy(channel)
    assert strategy is None
