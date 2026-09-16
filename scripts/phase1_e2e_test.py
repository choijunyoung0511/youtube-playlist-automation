"""Executable proof of the Phase 1 flow (spec section 25 test scenario):

10 concepts generated -> top 3 selected -> 1 approved -> music prompts generated.

Uses a dedicated sqlite file so it never touches the app's real data/app.db.
Run: ./.venv/bin/python scripts/phase1_e2e_test.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_PATH = PROJECT_ROOT / "data" / "phase1_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("AI_PROVIDER", "mock")

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Concept, ConceptStatus, Track  # noqa: E402
from app.providers.mock_provider import MockAiProvider  # noqa: E402
from app.seed import ensure_default_channel  # noqa: E402
from app.services.concept_service import ConceptService  # noqa: E402
from app.services.music_prompt_service import MusicPromptService  # noqa: E402


def line():
    print("-" * 78)


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    channel = ensure_default_channel(db)
    ai = MockAiProvider(seed=42)

    concept_service = ConceptService(db, ai)
    music_service = MusicPromptService(db, ai)

    print(f"Channel: {channel.name} ({channel.niche})")
    line()

    # Step 1: generate + evaluate 10 concepts
    concepts = concept_service.generate_and_evaluate(channel, count=10)
    assert len(concepts) == 10, f"expected 10 concepts, got {len(concepts)}"
    print(f"STEP 1: Generated and evaluated {len(concepts)} concepts:\n")
    for c in sorted(concepts, key=lambda c: c.evaluation_score, reverse=True):
        print(f"  [{c.evaluation_score:5.1f}] {c.concept_name}")
        print(f"          situation: {c.listening_situation}")
        print(f"          target: {c.target_audience} | genre: {c.genre} | mood: {c.mood}")
    line()

    # Step 2: select top 3
    top3 = concept_service.select_top(concepts, k=3)
    assert len(top3) == 3, f"expected 3 selected concepts, got {len(top3)}"
    selected_count = db.query(Concept).filter(Concept.status == ConceptStatus.SELECTED).count()
    rejected_count = db.query(Concept).filter(Concept.status == ConceptStatus.REJECTED).count()
    assert selected_count == 3, f"expected 3 SELECTED in DB, got {selected_count}"
    assert rejected_count == 7, f"expected 7 REJECTED in DB, got {rejected_count}"
    print("STEP 2: Top 3 concepts selected:\n")
    for c in top3:
        print(f"  [{c.evaluation_score:5.1f}] {c.concept_name}")
        print(f"          reasoning: {c.evaluation_reasoning}")
    line()

    # Step 3: approve one concept (the top-ranked one)
    chosen = top3[0]
    approved = concept_service.approve(chosen.id)
    assert approved.status == ConceptStatus.APPROVED, f"expected APPROVED, got {approved.status}"
    print(f"STEP 3: Approved concept -> '{approved.concept_name}' (id={approved.id}, status={approved.status.value})")
    line()

    # Step 4: generate music prompts for the approved concept
    tracks = music_service.generate_tracks(approved, count=5)
    assert len(tracks) == 5, f"expected 5 tracks, got {len(tracks)}"
    db_tracks = db.query(Track).filter(Track.concept_id == approved.id).all()
    assert len(db_tracks) == 5, f"expected 5 tracks in DB, got {len(db_tracks)}"
    print(f"STEP 4: Generated {len(tracks)} music prompt candidates for '{approved.concept_name}':\n")
    for t in tracks:
        p = t.prompt
        print(f"  - {t.title} | bpm={p['bpm']} tempo={p['tempo']} energy={p['energy_level']}")
        print(f"    instruments: {', '.join(p['instruments'])}")
        print(f"    structure: {p['song_structure']}")
    line()

    print("PHASE 1 END-TO-END TEST: PASS")
    print(f"(test database written to {TEST_DB_PATH})")

    db.close()


if __name__ == "__main__":
    main()
