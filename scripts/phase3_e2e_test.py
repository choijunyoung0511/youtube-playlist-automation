"""Executable proof of the Phase 3 flow: order SELECTED tracks by
BPM/energy, cycle-fill them to a target duration, crossfade-assemble the
audio with ffmpeg, and render a 16:9 background video (spec sections 9-10).

This picks up after Phase 2's quality gate (already proven in
scripts/phase2_e2e_test.py) - to keep this test fast, 3 short (~5s)
synthetic tracks are marked SELECTED directly rather than re-running the
full upload+analysis pipeline. A small target_duration_sec (20s) is used
instead of a real 30-120 minute target so the test forces - and can
assert on - the repeat-cycling logic and finishes quickly; production
calls (the admin UI) use target_length_min (30/60/90/120) instead.

Uses a dedicated sqlite file, isolated from data/app.db and the other
phase test databases.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase3_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import PlaylistStatus, PlaylistTrack, TrackStatus  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402
from app.services.playlist_pipeline import build_and_render_playlist  # noqa: E402


def line():
    print("-" * 78)


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ffprobe_json(path: Path) -> dict:
    import json
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def make_short_track_audio(path: Path, freq: int, duration: int = 5) -> None:
    run_ffmpeg([
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
        "-af", "afade=t=in:st=0:d=0.3,afade=t=out:st={}:d=0.3,volume=0.3".format(duration - 0.3),
        str(path),
    ])


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    channel = ensure_default_channel(db)
    ai = MockAiProvider(seed=5)

    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=5)

    print(f"Approved concept: {approved.concept_name} (mood={approved.mood})")
    line()

    # Mark 3 tracks SELECTED directly with short, distinct audio + BPM/energy
    # so the ordering/repeat-fill logic has clearly separated inputs to sort.
    audio_dir = PROJECT_ROOT / "data" / "phase3_test_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    configs = [
        (tracks[0], 220, 60, "low"),
        (tracks[1], 330, 90, "medium"),
        (tracks[2], 440, 140, "high"),
    ]
    for track, freq, bpm, energy in configs:
        fixture = audio_dir / f"track_{track.id}.wav"
        make_short_track_audio(fixture, freq, duration=5)
        track.audio_path = str(fixture)
        track.duration_sec = 5
        track.bpm = bpm
        track.prompt = {**track.prompt, "energy_level": energy, "bpm": bpm}
        track.quality_status = TrackStatus.SELECTED
        track.quality_reason = "manually marked SELECTED for Phase 3 test (Phase 2 gate covered separately)"
    db.commit()

    print("SELECTED tracks for playlist building:")
    for track, freq, bpm, energy in configs:
        print(f"  - {track.title}: bpm={bpm} energy={energy} duration={track.duration_sec}s")
    line()

    audio_out_dir = PROJECT_ROOT / "data" / "phase3_test_playlist_audio"
    video_out_dir = PROJECT_ROOT / "data" / "phase3_test_playlist_video"

    # 3 tracks x 5s = 15s < 20s target -> forces at least one wrap-around,
    # proving PlaylistTrack's many-to-many design actually gets used to
    # reuse a track at a second position.
    playlist = build_and_render_playlist(
        db, approved,
        audio_dir=audio_out_dir,
        video_dir=video_out_dir,
        target_duration_sec=20,
        crossfade_sec=1,
    )

    track_links = sorted(playlist.track_links, key=lambda pt: pt.position)
    print(f"Playlist built: '{playlist.title}' status={playlist.status.value}")
    print(f"Sequence ({len(track_links)} entries, cycling {len(configs)} distinct tracks):")
    for link in track_links:
        print(f"  position {link.position}: track_id={link.track_id} bpm={link.track.bpm} energy={link.track.prompt['energy_level']}")
    line()

    # --- Assertions ---
    assert len(track_links) > len(configs), (
        f"expected the sequence to wrap around past {len(configs)} distinct tracks, got {len(track_links)} entries"
    )
    track_ids_used = [link.track_id for link in track_links]
    assert len(set(track_ids_used)) < len(track_ids_used), "expected at least one track to repeat (many-to-many reuse)"

    # BPM should trend monotonically (60 -> 90 -> 140) at least on the first pass,
    # proving the nearest-neighbor ordering did something other than DB insertion order.
    first_pass_bpms = [link.track.bpm for link in track_links[: len(configs)]]
    assert first_pass_bpms == sorted(first_pass_bpms), f"expected ascending BPM ordering, got {first_pass_bpms}"

    assert playlist.status == PlaylistStatus.READY
    assert playlist.audio_path and Path(playlist.audio_path).exists(), "playlist audio file missing"
    assert playlist.video_path and Path(playlist.video_path).exists(), "playlist video file missing"

    audio_probe = ffprobe_json(Path(playlist.audio_path))
    audio_duration = float(audio_probe["format"]["duration"])
    print(f"Assembled audio: {playlist.audio_path}")
    print(f"  duration={audio_duration:.1f}s (target was 20s, crossfades reduce raw sum slightly)")
    assert audio_duration >= 15, f"assembled audio suspiciously short: {audio_duration}s"

    video_probe = ffprobe_json(Path(playlist.video_path))
    video_stream = next(s for s in video_probe["streams"] if s["codec_type"] == "video")
    audio_stream = next(s for s in video_probe["streams"] if s["codec_type"] == "audio")
    print(f"Rendered video: {playlist.video_path}")
    print(f"  resolution={video_stream['width']}x{video_stream['height']} "
          f"video_duration={float(video_probe['format']['duration']):.1f}s "
          f"has_audio_stream={audio_stream is not None}")

    assert video_stream["width"] == 1280 and video_stream["height"] == 720, "expected 16:9 1280x720 output"
    assert audio_stream is not None, "rendered video has no audio track"
    line()

    print("PHASE 3 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
