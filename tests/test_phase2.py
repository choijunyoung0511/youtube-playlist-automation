"""Pytest version of the Phase 2 flow: upload audio -> librosa quality
analysis -> SELECTED/REJECTED. Lighter than scripts/phase2_e2e_test.py
(two cases instead of four) since the full four-rule demonstration is
already covered there; this just guards the wiring with pytest.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Track, TrackStatus
from app.providers.mock_provider import MockAiProvider
from app.providers.music.factory import get_music_generation_provider
from app.seed import ensure_default_channel
from app.services.concept_service import ConceptService
from app.services.music_prompt_service import MusicPromptService
from app.services.track_quality_service import TrackQualityService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def tmp_audio_dir():
    d = Path(tempfile.mkdtemp(prefix="phase2_pytest_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_wav(path: Path, af: str, duration: int):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}", "-af", af, str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _approved_tracks(db_session, count=2):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=3)
    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    return music_service.generate_tracks(approved, count=count)


def test_uploaded_clean_track_is_selected(db_session, tmp_audio_dir):
    tracks = _approved_tracks(db_session, count=1)
    track = tracks[0]

    fixture = tmp_audio_dir / "good.wav"
    _make_wav(fixture, "afade=t=in:st=0:d=1,volume=0.3", duration=200)

    provider = get_music_generation_provider("manual")
    dest = provider.save_uploaded_file(fixture, tmp_audio_dir / "storage", track.id)
    track.audio_path = dest
    track.generation_provider = provider.name
    db_session.commit()

    TrackQualityService(db_session).evaluate(track)

    assert track.quality_status == TrackStatus.SELECTED
    assert track.analysis_data["issues"] == []
    assert track.duration_sec == pytest.approx(200, abs=1)


def test_uploaded_track_with_long_intro_silence_is_rejected(db_session, tmp_audio_dir):
    tracks = _approved_tracks(db_session, count=2)
    track = tracks[1]

    fixture = tmp_audio_dir / "bad_intro.wav"
    _make_wav(fixture, "volume=0.3,adelay=15000", duration=180)

    provider = get_music_generation_provider("manual")
    dest = provider.save_uploaded_file(fixture, tmp_audio_dir / "storage", track.id)
    track.audio_path = dest
    track.generation_provider = provider.name
    db_session.commit()

    TrackQualityService(db_session).evaluate(track)

    assert track.quality_status == TrackStatus.REJECTED
    assert "인트로" in track.quality_reason
    assert db_session.query(Track).filter(Track.quality_status == TrackStatus.REJECTED).count() == 1
