from dataclasses import asdict

from sqlalchemy.orm import Session

from ..models import AiCostLog, Concept, Track, TrackStatus
from ..providers.base import AiProvider
from ..providers.types import AiUsage, ConceptCandidate


class MusicPromptService:
    def __init__(self, db: Session, ai_provider: AiProvider):
        self.db = db
        self.ai = ai_provider

    def generate_tracks(self, concept: Concept, count: int = 5) -> list[Track]:
        candidate = ConceptCandidate(
            concept_name=concept.concept_name,
            target_audience=concept.target_audience,
            listening_situation=concept.listening_situation,
            genre=concept.genre,
            sub_genre=concept.sub_genre,
            mood=concept.mood,
            visual_theme=concept.visual_theme,
            keywords=concept.keywords or [],
            estimated_playlist_length_min=concept.estimated_playlist_length_min,
            description=concept.description,
        )

        specs, usage = self.ai.generate_music_prompts(candidate, count)
        self._log_cost(usage, concept.id)

        tracks: list[Track] = []
        for spec in specs:
            track = Track(
                concept_id=concept.id,
                title=spec.title_hint,
                prompt=asdict(spec),
                duration_sec=spec.duration_target_sec,
                bpm=spec.bpm,
                quality_status=TrackStatus.GENERATED,
            )
            self.db.add(track)
            tracks.append(track)

        self.db.commit()
        for t in tracks:
            self.db.refresh(t)
        return tracks

    def _log_cost(self, usage: AiUsage, concept_id: int) -> None:
        log = AiCostLog(
            provider=usage.provider,
            model=usage.model,
            request_type="generate_music_prompts",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
            concept_id=concept_id,
        )
        self.db.add(log)
        self.db.commit()
