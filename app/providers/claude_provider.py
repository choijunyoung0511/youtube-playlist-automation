"""Real LLM-backed AiProvider using the Anthropic API.

Not used by default (AI_PROVIDER=mock). This class can be imported and
instantiated without ANTHROPIC_API_KEY set — the key is only required
the moment a method actually calls the API, so the rest of the app never
needs to know or care whether a key is configured.
"""

import json
from dataclasses import asdict

from .base import AiProvider
from .types import (
    AiUsage,
    ConceptCandidate,
    ConceptEvaluation,
    MusicPromptSpec,
    PerformanceInsights,
    VideoPerformanceRecord,
    YoutubeDescriptionSpec,
)

# Approximate USD per million tokens; update as Anthropic pricing changes.
# Used only for the cost-tracking log (spec section 22), not billing.
PRICING_PER_MTOK = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-opus-5": {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
}
DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


class ClaudeAiProvider(AiProvider):
    name = "claude"

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-5"):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if not self.api_key:
            raise RuntimeError(
                "ClaudeAiProvider requires ANTHROPIC_API_KEY to be set. "
                "Set AI_PROVIDER=mock to run without a real API key."
            )
        if self._client is None:
            import anthropic  # lazy import: not a hard dependency for mock-only runs

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _usage_from_response(self, response) -> AiUsage:
        pricing = PRICING_PER_MTOK.get(self.model, DEFAULT_PRICING)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]
        return AiUsage(
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=round(cost, 6),
        )

    def _call_json(self, system: str, user: str, max_tokens: int = 2000):
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        data = json.loads(text)
        return data, self._usage_from_response(response)

    def generate_concepts(self, channel_context: dict, count: int) -> tuple[list[ConceptCandidate], AiUsage]:
        system = (
            "You generate YouTube playlist concepts for a vocal-less mood-music channel. "
            "Each concept must center on a concrete real-world listening situation "
            "(e.g. 'rainy dawn coding session'), not a generic keyword mashup. "
            "If channel_context includes a performance_insights object (from analyzing past uploads' "
            "actual YouTube performance), let it bias roughly 30-40% of the candidates toward the "
            "recommended situations/genres/moods/BPM range - but NEVER copy a past concept name or "
            "title verbatim, and keep the rest of the batch exploring fresh territory. "
            "Respond ONLY with a JSON array, no prose, no markdown fences."
        )
        user = (
            f"Channel context: {json.dumps(channel_context, ensure_ascii=False)}\n"
            f"Generate {count} distinct playlist concept candidates. Each item must be a JSON object with keys: "
            "concept_name, target_audience, listening_situation, genre, sub_genre, mood, visual_theme, "
            "keywords (array of strings), estimated_playlist_length_min (one of 30/60/90/120), description."
        )
        data, usage = self._call_json(system, user, max_tokens=3000)
        candidates = [ConceptCandidate(**item) for item in data]
        return candidates, usage

    def evaluate_concepts(self, concepts: list[ConceptCandidate]) -> tuple[list[ConceptEvaluation], AiUsage]:
        system = (
            "You evaluate YouTube playlist concepts against these criteria (score 0-10 each): "
            "situation_clarity, target_audience_clarity, long_listen_justification, differentiation, "
            "branding_visual_ease, seriesability, genre_mood_focus. "
            "Respond ONLY with a JSON array aligned by index to the input, no prose."
        )
        user = json.dumps([asdict(c) for c in concepts], ensure_ascii=False)
        data, usage = self._call_json(system, user, max_tokens=3000)
        evaluations = []
        for idx, item in enumerate(data):
            breakdown = item["breakdown"]
            total_score = round(sum(breakdown.values()) / (len(breakdown) * 10) * 100, 1)
            evaluations.append(
                ConceptEvaluation(
                    concept_index=idx,
                    total_score=item.get("total_score", total_score),
                    breakdown=breakdown,
                    reasoning=item.get("reasoning", ""),
                )
            )
        return evaluations, usage

    def generate_music_prompts(self, concept: ConceptCandidate, count: int) -> tuple[list[MusicPromptSpec], AiUsage]:
        system = (
            "You write instrumental music-generation prompts (for tools like Suno) for a vocal-less "
            "mood-music YouTube channel. NEVER reference real artists or existing song titles/melodies. "
            "Respond ONLY with a JSON array, no prose."
        )
        user = (
            f"Concept: {json.dumps(asdict(concept), ensure_ascii=False)}\n"
            f"Generate {count} distinct music prompt candidates. Each item must be a JSON object with keys: "
            "title_hint, genre, sub_genre, mood, bpm, tempo, instruments (array), energy_level, "
            "song_structure, production_style, vocal (must be false), duration_target_sec, loopability, "
            "negative_prompt."
        )
        data, usage = self._call_json(system, user, max_tokens=3000)
        specs = [MusicPromptSpec(**item) for item in data]
        return specs, usage

    def generate_youtube_titles(self, concept: ConceptCandidate, count: int = 5) -> tuple[list[str], AiUsage]:
        system = (
            "You write YouTube titles for a vocal-less mood-music playlist video. Titles must center on the "
            "concrete listening situation (e.g. 'Rainy Night Coding ☁️ Deep Focus Jazz for Programming'), "
            "not generic filler like 'AI Generated Jazz #15'. Mix Korean/English naturally where it fits the "
            "channel. Respond ONLY with a JSON array of strings, no prose."
        )
        user = f"Concept: {json.dumps(asdict(concept), ensure_ascii=False)}\nGenerate {count} distinct title candidates."
        data, usage = self._call_json(system, user, max_tokens=1000)
        return list(data), usage

    def generate_description(
        self, concept: ConceptCandidate, chosen_title: str, playlist_duration_min: int
    ) -> tuple[YoutubeDescriptionSpec, AiUsage]:
        system = (
            "You write a YouTube description for a vocal-less mood-music playlist. No spammy keyword "
            "repetition. Respond ONLY with a JSON object with keys: description, hashtags (array), "
            "keywords (array), playlist_category, thumbnail_text."
        )
        user = (
            f"Concept: {json.dumps(asdict(concept), ensure_ascii=False)}\n"
            f"Chosen title: {chosen_title}\nPlaylist duration: {playlist_duration_min} minutes."
        )
        data, usage = self._call_json(system, user, max_tokens=1500)
        return YoutubeDescriptionSpec(**data), usage

    def generate_thumbnail_prompt(self, concept: ConceptCandidate, theme: dict) -> tuple[str, AiUsage]:
        system = (
            "You write an image-generation prompt for a YouTube thumbnail, following the channel's brand "
            "theme exactly for visual consistency. No real-world brand logos, no named real people or "
            "copyrighted characters. Respond ONLY with the prompt text, no JSON, no prose commentary."
        )
        user = f"Concept: {json.dumps(asdict(concept), ensure_ascii=False)}\nBrand theme: {json.dumps(theme, ensure_ascii=False)}"
        client = self._get_client()
        response = client.messages.create(
            model=self.model, max_tokens=500, system=system, messages=[{"role": "user", "content": user}]
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return text, self._usage_from_response(response)

    def analyze_performance(
        self, top_records: list[VideoPerformanceRecord], all_records: list[VideoPerformanceRecord]
    ) -> tuple[PerformanceInsights, AiUsage]:
        system = (
            "You analyze YouTube performance data for a vocal-less mood-music channel and extract "
            "transferable patterns for future content strategy. Weigh views, CTR, average view "
            "duration, percentage viewed, watch time, subscriber conversion, and comments together - "
            "never rank by views alone. NEVER suggest literally repeating a past concept name, title, "
            "or thumbnail text - only extract patterns (situation type, genre, mood, BPM range, title "
            "structure, thumbnail style, video length) that should inform NEW variations. "
            "Respond ONLY with a JSON object with keys: summary, recommended_situations (array), "
            "recommended_genres (array), recommended_moods (array), bpm_min, bpm_max, "
            "title_structure_notes, thumbnail_style_notes, video_length_minutes_recommendation, "
            "things_to_avoid_repeating."
        )
        user = json.dumps(
            {
                "top_performing_videos": [asdict(r) for r in top_records],
                "all_videos_for_context": [asdict(r) for r in all_records],
            },
            ensure_ascii=False,
        )
        data, usage = self._call_json(system, user, max_tokens=2000)
        return PerformanceInsights(**data), usage
