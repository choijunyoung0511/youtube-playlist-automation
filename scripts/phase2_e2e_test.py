"""Executable proof of the Phase 2 flow: upload audio for an approved
concept's tracks -> librosa quality analysis -> SELECTED/REJECTED with
concrete reasons (spec sections 7-9).

Real Suno output isn't available in this environment, so this synthesizes
4 short WAV fixtures with ffmpeg: one clean track and three that each trip
a different quality rule (long intro silence, an abrupt volume jump, and
too-short length vs. the prompt's duration target). This exercises the
exact same upload -> TrackQualityService.evaluate() path the admin UI's
/concepts/{id}/tracks/{id}/upload endpoint uses.

Uses a dedicated sqlite file, isolated from data/app.db and from
scripts/phase1_e2e_test.py's database.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase2_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Track, TrackStatus  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.providers.music.factory import get_music_generation_provider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402
from app.services.track_quality_service import TrackQualityService  # noqa: E402


def line():
    print("-" * 78)


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synthesize_fixtures(tmp_dir: Path) -> dict[str, Path]:
    good = tmp_dir / "good.wav"
    bad_intro = tmp_dir / "bad_intro.wav"
    bad_jump = tmp_dir / "bad_jump.wav"
    too_short = tmp_dir / "too_short.wav"

    # Clean track: constant tone with a short fade-in. No deliberate
    # amplitude modulation - the analyzer's near-flat-envelope guard means
    # a stable ambient/pad-style loudness contour should not be mistaken
    # for a "short loop repeated" problem.
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=220:duration=200",
        "-af", "afade=t=in:st=0:d=1,volume=0.3",
        str(good),
    ])

    # 15s of true silence prepended -> trips the intro-silence rule (>8s).
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=220:duration=180",
        "-af", "volume=0.3,adelay=15000",
        str(bad_intro),
    ])

    # 20s only, vs a 180-240s prompt target -> trips the duration-mismatch rule.
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=220:duration=20",
        "-af", "volume=0.3",
        str(too_short),
    ])

    # 170s at a normal level, then a short 10s spike far louder -> trips the
    # abrupt volume-jump rule. The spike is a minority of the track (like a
    # real mixing glitch would be) so it shows up clearly against the
    # median baseline, unlike a 50/50 split which drags the median with it.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=170",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
            "-filter_complex",
            "[0]volume=0.3[a];[1]volume=2.5[b];[a][b]concat=n=2:v=0:a=1[out]",
            "-map", "[out]", str(bad_jump),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    return {"good": good, "bad_intro": bad_intro, "bad_jump": bad_jump, "too_short": too_short}


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    channel = ensure_default_channel(db)
    ai = MockAiProvider(seed=11)

    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)
    quality_service = TrackQualityService(db)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=5)

    print(f"Approved concept: {approved.concept_name}")
    print(f"Generated {len(tracks)} track prompt candidates; uploading synthetic test audio for 4 of them.")
    line()

    tmp_dir = Path(tempfile.mkdtemp(prefix="phase2_audio_"))
    try:
        fixtures = synthesize_fixtures(tmp_dir)
        provider = get_music_generation_provider("manual")
        storage_dir = PROJECT_ROOT / "data" / "audio_test"

        assignments = [
            (tracks[0], fixtures["good"], "expected SELECTED"),
            (tracks[1], fixtures["bad_intro"], "expected REJECTED - intro silence"),
            (tracks[2], fixtures["bad_jump"], "expected REJECTED - volume jump"),
            (tracks[3], fixtures["too_short"], "expected REJECTED - too short"),
        ]

        for track, fixture_path, expectation in assignments:
            dest = provider.save_uploaded_file(fixture_path, storage_dir, track.id)
            track.audio_path = dest
            track.generation_provider = provider.name
            db.commit()

            quality_service.evaluate(track)
            print(f"[{track.quality_status.value:9s}] {track.title}  ({expectation})")
            print(f"           reason: {track.quality_reason}")
            print(f"           metrics: {track.analysis_data}")
        line()

        selected = db.query(Track).filter(Track.quality_status == TrackStatus.SELECTED).count()
        rejected = db.query(Track).filter(Track.quality_status == TrackStatus.REJECTED).count()
        assert selected == 1, f"expected 1 SELECTED, got {selected}"
        assert rejected == 3, f"expected 3 REJECTED, got {rejected}"

        good_track = assignments[0][0]
        assert good_track.quality_status == TrackStatus.SELECTED

        intro_track = assignments[1][0]
        assert intro_track.quality_status == TrackStatus.REJECTED
        assert "인트로" in intro_track.quality_reason

        jump_track = assignments[2][0]
        assert jump_track.quality_status == TrackStatus.REJECTED
        assert "볼륨" in jump_track.quality_reason

        short_track = assignments[3][0]
        assert short_track.quality_status == TrackStatus.REJECTED
        assert "길이" in short_track.quality_reason

        print("PHASE 2 END-TO-END TEST: PASS")
        print(f"(test database written to {TEST_DB_PATH})")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        db.close()


if __name__ == "__main__":
    main()
