from abc import ABC, abstractmethod

from .types import (
    AiUsage,
    ConceptCandidate,
    ConceptEvaluation,
    MusicPromptSpec,
    PerformanceInsights,
    VideoPerformanceRecord,
    YoutubeDescriptionSpec,
)


class AiProvider(ABC):
    """Provider-agnostic AI interface (spec section 21).

    Concrete providers (Mock, Claude, future OpenAI/etc.) must not leak
    provider-specific concepts into callers — everything crosses this
    boundary as the dataclasses in types.py.
    """

    name: str

    @abstractmethod
    def generate_concepts(self, channel_context: dict, count: int) -> tuple[list[ConceptCandidate], AiUsage]:
        ...

    @abstractmethod
    def evaluate_concepts(self, concepts: list[ConceptCandidate]) -> tuple[list[ConceptEvaluation], AiUsage]:
        ...

    @abstractmethod
    def generate_music_prompts(self, concept: ConceptCandidate, count: int) -> tuple[list[MusicPromptSpec], AiUsage]:
        ...

    @abstractmethod
    def generate_youtube_titles(self, concept: ConceptCandidate, count: int) -> tuple[list[str], AiUsage]:
        ...

    @abstractmethod
    def generate_description(
        self, concept: ConceptCandidate, chosen_title: str, playlist_duration_min: int
    ) -> tuple[YoutubeDescriptionSpec, AiUsage]:
        ...

    @abstractmethod
    def generate_thumbnail_prompt(self, concept: ConceptCandidate, theme: dict) -> tuple[str, AiUsage]:
        ...

    @abstractmethod
    def analyze_performance(
        self, top_records: list[VideoPerformanceRecord], all_records: list[VideoPerformanceRecord]
    ) -> tuple[PerformanceInsights, AiUsage]:
        ...
