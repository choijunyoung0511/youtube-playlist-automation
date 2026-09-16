"""Executable proof of the Phase 4 flow: generate YouTube titles/description/
thumbnail for a built Playlist, let the admin pick a title, then approve or
reject (spec sections 11-14).

Picks up after Phase 3 (playlist audio+video already proven in
scripts/phase3_e2e_test.py) - builds a small playlist the same fast way
(short synthetic tracks, small target_duration_sec) so this test finishes
in seconds, then exercises the actual Phase 4 code path on top of it.

Uses a dedicated sqlite file, isolated from data/app.db and the other
phase test databases.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase4_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import PlaylistStatus, TrackStatus  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402
from app.services.playlist_pipeline import build_and_render_playlist  # noqa: E402
from app.services.playlist_service import PlaylistService  # noqa: E402
from app.services.youtube_metadata_service import YoutubeMetadataService, ensure_thumbnail_theme  # noqa: E402


def line():
    print("-" * 78)


def make_short_track_audio(path: Path, freq: int, duration: int = 5) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
         "-af", "volume=0.3", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    channel = ensure_default_channel(db)
    ai = MockAiProvider(seed=13)

    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=3)

    audio_dir = PROJECT_ROOT / "data" / "phase4_test_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for i, track in enumerate(tracks):
        fixture = audio_dir / f"track_{track.id}.wav"
        make_short_track_audio(fixture, freq=220 + i * 110, duration=5)
        track.audio_path = str(fixture)
        track.duration_sec = 5
        track.bpm = 60 + i * 40
        track.prompt = {**track.prompt, "bpm": track.bpm}
        track.quality_status = TrackStatus.SELECTED
    db.commit()

    playlist = build_and_render_playlist(
        db, approved,
        audio_dir=PROJECT_ROOT / "data" / "phase4_test_playlist_audio",
        video_dir=PROJECT_ROOT / "data" / "phase4_test_playlist_video",
        target_duration_sec=12,
        crossfade_sec=1,
    )
    print(f"Playlist built: '{playlist.title}' status={playlist.status.value}")
    line()

    # --- Phase 4 starts here ---
    thumbnail_dir = PROJECT_ROOT / "data" / "phase4_test_thumbnails"
    metadata_service = YoutubeMetadataService(db, ai)
    playlist = metadata_service.generate_all(playlist, thumbnail_dir)

    assert playlist.status == PlaylistStatus.REVIEW_REQUIRED, f"expected REVIEW_REQUIRED, got {playlist.status}"
    assert playlist.title_candidates and len(playlist.title_candidates) == 5, "expected 5 title candidates"
    assert playlist.chosen_title in playlist.title_candidates

    print(f"STEP 1: Generated metadata, status={playlist.status.value}")
    print("Title candidates:")
    for t in playlist.title_candidates:
        marker = " <- default" if t == playlist.chosen_title else ""
        print(f"  - {t}{marker}")
    line()

    # Admin picks a different title candidate than the default.
    alternate_title = next(t for t in playlist.title_candidates if t != playlist.chosen_title)
    playlist = metadata_service.choose_title(playlist, alternate_title)
    assert playlist.chosen_title == alternate_title

    print(f"STEP 2: Admin selected title -> '{playlist.chosen_title}'")
    print(f"Description: {playlist.youtube_description[:120]}...")
    print(f"Hashtags: {playlist.hashtags}")
    print(f"Keywords: {playlist.keywords}")
    print(f"Category: {playlist.playlist_category}")
    line()

    assert playlist.thumbnail_path and Path(playlist.thumbnail_path).exists(), "thumbnail image missing"
    assert playlist.thumbnail_prompt, "thumbnail prompt missing"
    print(f"STEP 3: Thumbnail rendered at {playlist.thumbnail_path}")
    print(f"Thumbnail prompt: {playlist.thumbnail_prompt[:120]}...")
    line()

    theme = ensure_thumbnail_theme(db, channel.id)
    assert theme.channel_id == channel.id
    print(f"STEP 4: Channel ThumbnailTheme in use: visual_style='{theme.visual_style}'")
    line()

    # Regeneration paths (Regenerate Title / Regenerate Thumbnail admin buttons).
    old_candidates = playlist.title_candidates
    playlist = metadata_service.generate_titles(playlist)
    assert playlist.title_candidates is not None
    print("STEP 5: Regenerated title candidates via the same seeded mock provider (deterministic, so may repeat):")
    for t in playlist.title_candidates:
        print(f"  - {t}")
    line()

    # Final human approval gate (spec section 14) - REVIEW_REQUIRED -> APPROVED.
    playlist_service = PlaylistService(db)
    playlist = playlist_service.approve(playlist)
    assert playlist.status == PlaylistStatus.APPROVED, f"expected APPROVED, got {playlist.status}"
    print(f"STEP 6: Playlist approved -> status={playlist.status.value}")
    line()

    # Reject path, exercised on a second playlist so it doesn't clobber the approved one.
    approved2 = concept_service.approve(top3[1].id)
    tracks2 = music_service.generate_tracks(approved2, count=1)
    fixture2 = audio_dir / f"track_{tracks2[0].id}.wav"
    make_short_track_audio(fixture2, freq=550, duration=5)
    tracks2[0].audio_path = str(fixture2)
    tracks2[0].duration_sec = 5
    tracks2[0].quality_status = TrackStatus.SELECTED
    db.commit()

    playlist2 = build_and_render_playlist(
        db, approved2,
        audio_dir=PROJECT_ROOT / "data" / "phase4_test_playlist_audio",
        video_dir=PROJECT_ROOT / "data" / "phase4_test_playlist_video",
        target_duration_sec=6,
        crossfade_sec=0,
    )
    playlist2 = metadata_service.generate_all(playlist2, thumbnail_dir)
    playlist2 = playlist_service.reject(playlist2)
    assert playlist2.status == PlaylistStatus.REJECTED, f"expected REJECTED, got {playlist2.status}"
    print(f"STEP 7: Second playlist rejected -> status={playlist2.status.value}")
    line()

    print("PHASE 4 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
