"""Pytest version of the Phase 1 test scenario (spec section 25):
10 concepts -> top 3 selected -> 1 approved -> music prompts generated.

Runs against an isolated in-memory sqlite DB, independent of the app's
real data/app.db and of scripts/phase1_e2e_test.py's file-based DB.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Concept, ConceptStatus, Track
from app.providers.mock_provider import MockAiProvider
from app.seed import ensure_default_channel
from app.services.concept_service import ConceptService
from app.services.music_prompt_service import MusicPromptService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_phase1_end_to_end_flow(db_session):
    channel = ensure_default_channel(db_session)
    ai = MockAiProvider(seed=7)

    concept_service = ConceptService(db_session, ai)
    music_service = MusicPromptService(db_session, ai)

    concepts = concept_service.generate_and_evaluate(channel, count=10)
    assert len(concepts) == 10
    assert all(c.status == ConceptStatus.EVALUATED for c in concepts)
    assert all(c.evaluation_score is not None for c in concepts)

    top3 = concept_service.select_top(concepts, k=3)
    assert len(top3) == 3
    assert db_session.query(Concept).filter(Concept.status == ConceptStatus.SELECTED).count() == 3
    assert db_session.query(Concept).filter(Concept.status == ConceptStatus.REJECTED).count() == 7

    scores = [c.evaluation_score for c in top3]
    assert scores == sorted(scores, reverse=True)

    chosen = top3[0]
    approved = concept_service.approve(chosen.id)
    assert approved.status == ConceptStatus.APPROVED

    tracks = music_service.generate_tracks(approved, count=5)
    assert len(tracks) == 5
    assert all(t.quality_status.value == "GENERATED" for t in tracks)
    assert all(t.prompt["vocal"] is False for t in tracks)

    db_tracks = db_session.query(Track).filter(Track.concept_id == approved.id).all()
    assert len(db_tracks) == 5
