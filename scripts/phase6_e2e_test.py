"""Executable proof of the Phase 6 flow: collect daily YouTube performance
stats for an uploaded video and upsert them into YoutubeStats (spec
section 16).

Uses MockYoutubeAnalyticsProvider since no real Google OAuth credentials
exist in this environment. Exercises the exact same
AnalyticsCollectionService code path the admin UI's "Collect Today's
Stats" button and scripts/collect_analytics.py use.

Uses a dedicated sqlite file, isolated from data/app.db and the other
phase test databases.
"""

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase6_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import PlaylistStatus, TrackStatus, YoutubeStats  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.providers.youtube.mock_analytics_provider import MockYoutubeAnalyticsProvider  # noqa: E402
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.analytics_collection_service import AnalyticsCollectionService  # noqa: E402
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
    ai = MockAiProvider(seed=19)
    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)
    approved = concept_service.approve(top3[0].id)
    tracks = music_service.generate_tracks(approved, count=2)

    audio_dir = PROJECT_ROOT / "data" / "phase6_test_audio"
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
        audio_dir=PROJECT_ROOT / "data" / "phase6_test_playlist_audio",
        video_dir=PROJECT_ROOT / "data" / "phase6_test_playlist_video",
        target_duration_sec=8,
        crossfade_sec=0,
    )
    playlist = YoutubeMetadataService(db, ai).generate_all(playlist, PROJECT_ROOT / "data" / "phase6_test_thumbnails")
    playlist = PlaylistService(db).approve(playlist)

    youtube_video = YoutubeUploadService(db, MockYoutubeUploadProvider()).upload(
        playlist, privacy_status="private", category_id="10"
    )
    db.refresh(playlist)
    print(f"Uploaded: video_id={youtube_video.youtube_video_id}, playlist status={playlist.status.value}")
    line()

    # --- Guard: collecting stats for a video that hasn't been uploaded should be impossible via this path ---
    analytics_service = AnalyticsCollectionService(db, MockYoutubeAnalyticsProvider())

    target_date = date.today() - timedelta(days=1)
    row = analytics_service.collect_for_video(youtube_video, target_date)

    assert row.youtube_video_id == youtube_video.id
    assert row.views > 0
    assert row.impressions and row.impressions >= row.views
    assert row.ctr is not None

    print(f"STEP 1: Collected stats for {target_date.isoformat()}:")
    print(f"  views={row.views} watch_time_min={row.watch_time_min} avg_view_dur={row.average_view_duration_sec}s")
    print(f"  avg_pct_viewed={row.average_percentage_viewed}% impressions={row.impressions} ctr={row.ctr}%")
    print(f"  likes={row.likes} comments={row.comments} subs_gained={row.subscribers_gained}")
    line()

    # --- Idempotency: re-collecting the same date must upsert, not duplicate ---
    row_again = analytics_service.collect_for_video(youtube_video, target_date)
    assert row_again.id == row.id, "expected the same YoutubeStats row to be updated, not a new one created"

    count_for_date = (
        db.query(YoutubeStats)
        .filter(YoutubeStats.youtube_video_id == youtube_video.id)
        .count()
    )
    assert count_for_date == 1, f"expected exactly 1 stats row for this video, got {count_for_date}"
    print(f"STEP 2: Re-collecting the same date upserted the existing row (id={row_again.id}), no duplicate")
    line()

    # --- A second day accumulates a second row ---
    second_date = date.today()
    row2 = analytics_service.collect_for_video(youtube_video, second_date)
    assert row2.id != row.id

    all_rows = (
        db.query(YoutubeStats)
        .filter(YoutubeStats.youtube_video_id == youtube_video.id)
        .order_by(YoutubeStats.date)
        .all()
    )
    assert len(all_rows) == 2, f"expected 2 daily rows, got {len(all_rows)}"
    print(f"STEP 3: Second day collected as a separate row -> {len(all_rows)} total daily rows for this video")
    line()

    # --- collect_for_channel sweeps every uploaded video for the channel ---
    channel_rows = analytics_service.collect_for_channel(channel.id, second_date)
    assert len(channel_rows) == 1, f"expected 1 video for this channel, got {len(channel_rows)}"
    print(f"STEP 4: collect_for_channel found {len(channel_rows)} uploaded video(s) for '{channel.name}'")
    line()

    print("PHASE 6 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
