"""Recomputes and persists a channel's performance-derived content
strategy (spec section 17): rank uploaded videos by the composite score
from PerformanceAnalysisService, ask the AiProvider to extract
transferable patterns from the top performers, and save the result as
that channel's current ContentStrategy (replacing the previous one)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AiCostLog, Channel, ContentStrategy
from ..providers.base import AiProvider
from ..providers.types import AiUsage
from .performance_analysis_service import PerformanceAnalysisService

MIN_VIDEOS_FOR_STRATEGY = 1  # deliberately low for demo/testability; real use would want more data


class ContentStrategyService:
    def __init__(self, db: Session, ai_provider: AiProvider):
        self.db = db
        self.ai = ai_provider

    def refresh_strategy(self, channel: Channel) -> ContentStrategy | None:
        records = PerformanceAnalysisService(self.db).build_records(channel.id)
        if len(records) < MIN_VIDEOS_FOR_STRATEGY:
            return None

        top_count = max(1, round(len(records) * 0.3))
        top_records = records[:top_count]

        insights, usage = self.ai.analyze_performance(top_records, records)
        self._log_cost(usage)

        strategy = self.db.query(ContentStrategy).filter(ContentStrategy.channel_id == channel.id).first()
        if strategy is None:
            strategy = ContentStrategy(channel_id=channel.id)
            self.db.add(strategy)

        strategy.summary = insights.summary
        strategy.recommended_situations = insights.recommended_situations
        strategy.recommended_genres = insights.recommended_genres
        strategy.recommended_moods = insights.recommended_moods
        strategy.bpm_min = insights.bpm_min
        strategy.bpm_max = insights.bpm_max
        strategy.title_structure_notes = insights.title_structure_notes
        strategy.thumbnail_style_notes = insights.thumbnail_style_notes
        strategy.video_length_minutes_recommendation = insights.video_length_minutes_recommendation
        strategy.things_to_avoid_repeating = insights.things_to_avoid_repeating
        strategy.based_on_video_count = len(records)
        strategy.generated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(strategy)
        return strategy

    def _log_cost(self, usage: AiUsage) -> None:
        log = AiCostLog(
            provider=usage.provider,
            model=usage.model,
            request_type="analyze_performance",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
        )
        self.db.add(log)
        self.db.commit()
