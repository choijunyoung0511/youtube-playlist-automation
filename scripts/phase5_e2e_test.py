"""Executable proof of the Phase 5 flow: upload an APPROVED playlist to
YouTube and record the result (spec section 15).

Uses MockYoutubeUploadProvider since no real Google OAuth credentials
exist in this environment - see scripts/youtube_oauth_setup.py for how to
get real ones. This still exercises the exact same YoutubeUploadService
code path the admin UI's "Upload to YouTube" button uses; only the
provider implementation differs.

Uses a dedicated sqlite file, isolated from data/app.db and the other
phase test databases.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase5_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import PlaylistStatus, TrackStatus  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402
from app.services.playlist_pipeline import build_and_render_playlist  # noqa: E402
from app.services.playlist_service import PlaylistService  # noqa: E402
from app.services.youtube_metadata_service import YoutubeMetadataService  # noqa: E402
from app.services.youtube_upload_service import YoutubeUploadService  # noqa: E402


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
    channel.youtube_playlist_id = "PLtest1234567890"  # exercise the "add to playlist" path
    db.commit()

    ai = MockAiProvider(seed=17)
    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=2)

    audio_dir = PROJECT_ROOT / "data" / "phase5_test_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for i, track in enumerate(tracks):
        fixture = audio_dir / f"track_{track.id}.wav"
        make_short_track_audio(fixture, freq=220 + i * 110, duration=5)
        track.audio_path = str(fixture)
        track.duration_sec = 5
        track.quality_status = TrackStatus.SELECTED
    db.commit()

    playlist = build_and_render_playlist(
        db, approved,
        audio_dir=PROJECT_ROOT / "data" / "phase5_test_playlist_audio",
        video_dir=PROJECT_ROOT / "data" / "phase5_test_playlist_video",
        target_duration_sec=8,
        crossfade_sec=0,
    )

    metadata_service = YoutubeMetadataService(db, ai)
    playlist = metadata_service.generate_all(playlist, PROJECT_ROOT / "data" / "phase5_test_thumbnails")
    print(f"Playlist ready for review: '{playlist.title}' status={playlist.status.value}")
    line()

    # --- Guard: uploading before approval must fail ---
    upload_service = YoutubeUploadService(db, MockYoutubeUploadProvider())
    try:
        upload_service.upload(playlist, privacy_status="private", category_id="10")
        raise AssertionError("expected upload to be rejected before APPROVED")
    except ValueError as e:
        print(f"STEP 1: Upload correctly rejected before approval -> {e}")
    line()

    # --- Approve, then upload ---
    playlist = PlaylistService(db).approve(playlist)
    assert playlist.status == PlaylistStatus.APPROVED
    print(f"STEP 2: Playlist approved -> status={playlist.status.value}")
    line()

    youtube_video = upload_service.upload(playlist, privacy_status="private", category_id="10")
    db.refresh(playlist)

    assert playlist.status == PlaylistStatus.UPLOADED, f"expected UPLOADED, got {playlist.status}"
    assert youtube_video.youtube_video_id.startswith("mock")
    assert youtube_video.title == playlist.chosen_title

    print(f"STEP 3: Uploaded -> status={playlist.status.value}")
    print(f"  YouTube video ID: {youtube_video.youtube_video_id}")
    print(f"  Title recorded: {youtube_video.title}")
    print(f"  Channel target playlist: {channel.youtube_playlist_id} (added_to_playlist assumed True since it was set)")
    line()

    # --- Re-upload should update the same YoutubeVideo row, not create a duplicate ---
    from app.models import YoutubeVideo
    playlist.status = PlaylistStatus.APPROVED  # simulate a re-approval / re-upload scenario
    db.commit()
    upload_service.upload(playlist, privacy_status="unlisted", category_id="10")
    video_rows = db.query(YoutubeVideo).filter(YoutubeVideo.playlist_id == playlist.id).count()
    assert video_rows == 1, f"expected exactly 1 YoutubeVideo row after re-upload, got {video_rows}"
    print(f"STEP 4: Re-upload kept a single YoutubeVideo row (count={video_rows}), not a duplicate")
    line()

    print("PHASE 5 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
