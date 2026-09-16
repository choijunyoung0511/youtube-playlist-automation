"""Pytest version of the Phase 3 flow: order + repeat-fill SELECTED
tracks into a Playlist, assemble crossfaded audio, render a 16:9 video.
Mirrors scripts/phase3_e2e_test.py but as a single fast assertion-based
case (short fixtures, small target duration).
"""

import json
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
    d = Path(tempfile.mkdtemp(prefix="phase3_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_short_audio(path: Path, freq: int, duration: int = 4):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _ffprobe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_build_and_render_playlist(db_session, tmp_dir):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=9)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=3)

    for i, track in enumerate(tracks):
        fixture = tmp_dir / f"track_{track.id}.wav"
        _make_short_audio(fixture, freq=220 + i * 110, duration=4)
        track.audio_path = str(fixture)
        track.duration_sec = 4
        track.bpm = 60 + i * 40
        track.prompt = {**track.prompt, "bpm": track.bpm}
        track.quality_status = TrackStatus.SELECTED
    db_session.commit()

    playlist = build_and_render_playlist(
        db_session, approved,
        audio_dir=tmp_dir / "audio_out",
        video_dir=tmp_dir / "video_out",
        target_duration_sec=15,  # 3 tracks x 4s = 12s < 15s -> forces a wrap-around
        crossfade_sec=1,
    )

    assert playlist.status == PlaylistStatus.READY
    track_links = sorted(playlist.track_links, key=lambda pt: pt.position)
    assert len(track_links) > 3, "expected the sequence to wrap past the 3 distinct tracks"

    assert Path(playlist.audio_path).exists()
    assert Path(playlist.video_path).exists()

    video_info = _ffprobe(Path(playlist.video_path))
    video_stream = next(s for s in video_info["streams"] if s["codec_type"] == "video")
    audio_stream = next((s for s in video_info["streams"] if s["codec_type"] == "audio"), None)
    assert (video_stream["width"], video_stream["height"]) == (1280, 720)
    assert audio_stream is not None
