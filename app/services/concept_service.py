from dataclasses import asdict

from sqlalchemy.orm import Session

from ..models import AiCostLog, Channel, Concept, ConceptStatus, ContentStrategy
from ..providers.base import AiProvider
from ..providers.types import AiUsage


class ConceptService:
    def __init__(self, db: Session, ai_provider: AiProvider):
        self.db = db
        self.ai = ai_provider

    def generate_and_evaluate(self, channel: Channel, count: int = 10) -> list[Concept]:
        channel_context = {
            "name": channel.name,
            "niche": channel.niche,
            "description": channel.description,
        }

        strategy = self.db.query(ContentStrategy).filter(ContentStrategy.channel_id == channel.id).first()
        if strategy is not None:
            channel_context["performance_insights"] = {
                "summary": strategy.summary,
                "recommended_situations": strategy.recommended_situations or [],
                "recommended_genres": strategy.recommended_genres or [],
                "recommended_moods": strategy.recommended_moods or [],
                "bpm_min": strategy.bpm_min,
                "bpm_max": strategy.bpm_max,
                "video_length_minutes_recommendation": strategy.video_length_minutes_recommendation,
                "things_to_avoid_repeating": strategy.things_to_avoid_repeating,
            }

        candidates, gen_usage = self.ai.generate_concepts(channel_context, count)
        self._log_cost(gen_usage, "generate_concepts")

        evaluations, eval_usage = self.ai.evaluate_concepts(candidates)
        self._log_cost(eval_usage, "evaluate_concepts")

        eval_by_index = {e.concept_index: e for e in evaluations}

        concepts: list[Concept] = []
        for idx, candidate in enumerate(candidates):
            evaluation = eval_by_index.get(idx)
            concept = Concept(
                channel_id=channel.id,
                concept_name=candidate.concept_name,
                target_audience=candidate.target_audience,
                listening_situation=candidate.listening_situation,
                genre=candidate.genre,
                sub_genre=candidate.sub_genre,
                mood=candidate.mood,
                visual_theme=candidate.visual_theme,
                keywords=candidate.keywords,
                estimated_playlist_length_min=candidate.estimated_playlist_length_min,
                description=candidate.description,
                status=ConceptStatus.EVALUATED,
                evaluation_score=evaluation.total_score if evaluation else None,
                evaluation_breakdown=evaluation.breakdown if evaluation else None,
                evaluation_reasoning=evaluation.reasoning if evaluation else None,
            )
            self.db.add(concept)
            concepts.append(concept)

        self.db.commit()
        for c in concepts:
            self.db.refresh(c)
        return concepts

    def select_top(self, concepts: list[Concept], k: int = 3) -> list[Concept]:
        ranked = sorted(concepts, key=lambda c: (c.evaluation_score or 0), reverse=True)
        top = ranked[:k]
        rest = ranked[k:]

        for c in top:
            c.status = ConceptStatus.SELECTED
        for c in rest:
            c.status = ConceptStatus.REJECTED

        self.db.commit()
        return top

    def approve(self, concept_id: int) -> Concept:
        concept = self.db.get(Concept, concept_id)
        if concept is None:
            raise ValueError(f"Concept {concept_id} not found")
        concept.status = ConceptStatus.APPROVED
        self.db.commit()
        self.db.refresh(concept)
        return concept

    def _log_cost(self, usage: AiUsage, request_type: str) -> None:
        log = AiCostLog(
            provider=usage.provider,
            model=usage.model,
            request_type=request_type,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
        )
        self.db.add(log)
        self.db.commit()
