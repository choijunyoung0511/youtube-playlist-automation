"""Executable proof of the Phase 7 flow: rank uploaded videos by real
accumulated performance, extract a content strategy from the winners, and
show it biasing (not literally repeating) the next concept batch (spec
section 17).

Directly writes two videos' YoutubeStats with deliberately different
performance levels (rather than relying on MockYoutubeAnalyticsProvider's
semi-random per-date numbers, which Phase 6 already proved) so the
ranking and downstream bias can be asserted deterministically.

Uses a dedicated sqlite file, isolated from data/app.db and the other
phase test databases.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase7_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import ContentStrategy, TrackStatus, YoutubeStats  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.providers.youtube.mock_provider import MockYoutubeUploadProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.content_strategy_service import ContentStrategyService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402
from app.services.performance_analysis_service import PerformanceAnalysisService  # noqa: E402
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


def upload_one(db, ai, concept_service, music_service, concept, audio_dir, freq, label):
    tracks = music_service.generate_tracks(concept, count=1)
    fixture = audio_dir / f"track_{tracks[0].id}.wav"
    make_short_track_audio(fixture, freq=freq, duration=5)
    tracks[0].audio_path = str(fixture)
    tracks[0].duration_sec = 5
    tracks[0].bpm = freq // 3  # arbitrary but distinct per concept, just needs to be non-null
    tracks[0].prompt = {**tracks[0].prompt, "bpm": tracks[0].bpm}
    tracks[0].quality_status = TrackStatus.SELECTED
    db.commit()

    playlist = build_and_render_playlist(
        db, concept,
        audio_dir=PROJECT_ROOT / "data" / f"phase7_test_playlist_audio_{label}",
        video_dir=PROJECT_ROOT / "data" / f"phase7_test_playlist_video_{label}",
        target_duration_sec=5,
        crossfade_sec=0,
    )
    playlist = YoutubeMetadataService(db, ai).generate_all(playlist, PROJECT_ROOT / "data" / "phase7_test_thumbnails")
    playlist = PlaylistService(db).approve(playlist)
    youtube_video = YoutubeUploadService(db, MockYoutubeUploadProvider()).upload(
        playlist, privacy_status="private", category_id="10"
    )
    return playlist, youtube_video


def write_stats(db, youtube_video, *, views, ctr, pct_viewed, subs, comments, days=3):
    for i in range(days):
        row = YoutubeStats(
            youtube_video_id=youtube_video.id,
            date=datetime.utcnow() - timedelta(days=i),
            views=views,
            watch_time_min=views * 3.0,
            average_view_duration_sec=180.0,
            average_percentage_viewed=pct_viewed,
            impressions=views * 8,
            ctr=ctr,
            likes=views // 10,
            comments=comments,
            subscribers_gained=subs,
        )
        db.add(row)
    db.commit()


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    channel = ensure_default_channel(db)
    ai = MockAiProvider(seed=23)
    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    top3 = concept_service.select_top(concepts, k=3)

    winner_concept = concept_service.approve(top3[0].id)
    loser_concept = concept_service.approve(top3[1].id)

    audio_dir = PROJECT_ROOT / "data" / "phase7_test_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    winner_playlist, winner_video = upload_one(db, ai, concept_service, music_service, winner_concept, audio_dir, 220, "winner")
    loser_playlist, loser_video = upload_one(db, ai, concept_service, music_service, loser_concept, audio_dir, 440, "loser")

    write_stats(db, winner_video, views=5000, ctr=9.5, pct_viewed=78.0, subs=40, comments=60)
    write_stats(db, loser_video, views=80, ctr=1.2, pct_viewed=15.0, subs=0, comments=1)

    print(f"Winner concept: {winner_concept.concept_name} (genre={winner_concept.genre}, mood={winner_concept.mood})")
    print(f"Loser concept:  {loser_concept.concept_name} (genre={loser_concept.genre}, mood={loser_concept.mood})")
    line()

    # --- Step 1: scoring ranks the winner first ---
    records = PerformanceAnalysisService(db).build_records(channel.id)
    assert len(records) == 2, f"expected 2 performance records, got {len(records)}"
    assert records[0].playlist_id == winner_playlist.id, "expected the high-performing video to rank first"
    assert records[0].score > records[1].score

    print(f"STEP 1: Ranked by score -> #1 playlist_id={records[0].playlist_id} score={records[0].score} "
          f"| #2 playlist_id={records[1].playlist_id} score={records[1].score}")
    line()

    # --- Step 2: strategy extraction reflects the winner, not the loser ---
    strategy = ContentStrategyService(db, ai).refresh_strategy(channel)
    assert strategy is not None
    assert winner_concept.genre in strategy.recommended_genres, (
        f"expected winner genre '{winner_concept.genre}' in {strategy.recommended_genres}"
    )
    assert loser_concept.genre not in strategy.recommended_genres or winner_concept.genre == loser_concept.genre, (
        "expected the strategy to favor the winner's genre, not the loser's"
    )

    print(f"STEP 2: Strategy refreshed (based_on_video_count={strategy.based_on_video_count})")
    print(f"  recommended_situations={strategy.recommended_situations}")
    print(f"  recommended_genres={strategy.recommended_genres}")
    print(f"  recommended_moods={strategy.recommended_moods}")
    print(f"  bpm_range=({strategy.bpm_min}, {strategy.bpm_max})")
    print(f"  summary: {strategy.summary}")
    line()

    # --- Step 3: the next concept batch is biased toward the winner, but not a clone of it ---
    next_batch = concept_service.generate_and_evaluate(channel, count=10)

    matching_genre_or_mood = [
        c for c in next_batch
        if c.genre in strategy.recommended_genres or c.mood in strategy.recommended_moods
    ]
    exact_name_matches = [c for c in next_batch if c.concept_name == winner_concept.concept_name]

    assert len(matching_genre_or_mood) >= 1, "expected at least some bias toward the winning genre/mood"
    assert len(matching_genre_or_mood) < len(next_batch), (
        "expected the batch to still explore fresh combinations, not be 100% biased"
    )
    assert not exact_name_matches, "expected no concept to literally repeat the winning concept's exact name"

    print(f"STEP 3: New batch of {len(next_batch)} concepts -> "
          f"{len(matching_genre_or_mood)} biased toward winning genre/mood, "
          f"{len(next_batch) - len(matching_genre_or_mood)} fresh exploration, "
          f"0 exact-name repeats of the winner")
    for c in next_batch:
        tag = "[BIASED]" if c in matching_genre_or_mood else "[fresh] "
        print(f"  {tag} {c.concept_name}  (genre={c.genre}, mood={c.mood})")
    line()

    print("PHASE 7 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
