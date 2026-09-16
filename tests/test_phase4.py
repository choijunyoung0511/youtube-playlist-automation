"""Pytest version of the Phase 4 flow: generate YouTube titles/description/
thumbnail for a built Playlist, pick a title, then approve/reject.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PlaylistStatus, TrackStatus
from app.providers.mock_provider import MockAiProvider
from app.seed import ensure_default_channel
from app.services.concept_service import ConceptService
from app.services.music_prompt_service import MusicPromptService
from app.services.playlist_pipeline import build_and_render_playlist
from app.services.playlist_service import PlaylistService
from app.services.youtube_metadata_service import YoutubeMetadataService, ensure_thumbnail_theme


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
    d = Path(tempfile.mkdtemp(prefix="phase4_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_short_audio(path: Path, freq: int, duration: int = 5):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _built_playlist(db_session, tmp_dir, seed=21, track_count=3, target_duration_sec=12):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=seed)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=track_count)

    for i, track in enumerate(tracks):
        fixture = tmp_dir / f"track_{track.id}.wav"
        _make_short_audio(fixture, freq=220 + i * 110, duration=5)
        track.audio_path = str(fixture)
        track.duration_sec = 5
        track.quality_status = TrackStatus.SELECTED
    db_session.commit()

    return build_and_render_playlist(
        db_session, approved,
        audio_dir=tmp_dir / "audio_out",
        video_dir=tmp_dir / "video_out",
        target_duration_sec=target_duration_sec,
        crossfade_sec=1,
    ), ai


def test_generate_metadata_and_approve(db_session, tmp_dir):
    playlist, ai = _built_playlist(db_session, tmp_dir)

    service = YoutubeMetadataService(db_session, ai)
    playlist = service.generate_all(playlist, tmp_dir / "thumbnails")

    assert playlist.status == PlaylistStatus.REVIEW_REQUIRED
    assert len(playlist.title_candidates) == 5
    assert playlist.chosen_title in playlist.title_candidates
    assert playlist.youtube_description
    assert playlist.hashtags and playlist.keywords
    assert Path(playlist.thumbnail_path).exists()
    assert playlist.thumbnail_prompt

    alt_title = next(t for t in playlist.title_candidates if t != playlist.chosen_title)
    playlist = service.choose_title(playlist, alt_title)
    assert playlist.chosen_title == alt_title

    playlist = PlaylistService(db_session).approve(playlist)
    assert playlist.status == PlaylistStatus.APPROVED


def test_reject_playlist(db_session, tmp_dir):
    playlist, ai = _built_playlist(db_session, tmp_dir, seed=22)
    service = YoutubeMetadataService(db_session, ai)
    playlist = service.generate_all(playlist, tmp_dir / "thumbnails")

    playlist = PlaylistService(db_session).reject(playlist)
    assert playlist.status == PlaylistStatus.REJECTED


def test_thumbnail_theme_is_per_channel(db_session, tmp_dir):
    channel = ensure_default_channel(db_session)
    theme = ensure_thumbnail_theme(db_session, channel.id)
    assert theme.channel_id == channel.id

    theme_again = ensure_thumbnail_theme(db_session, channel.id)
    assert theme_again.id == theme.id  # idempotent, not recreated
