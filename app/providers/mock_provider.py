"""Deterministic, no-API-key AI provider.

Used as the default (AI_PROVIDER=mock) so the whole pipeline can be built,
run and tested before any real LLM cost is incurred. It is intentionally
template + heuristic based rather than random keyword soup: every concept
is anchored to a concrete listening situation, matching spec section 3's
"good example vs bad example" distinction.
"""

from __future__ import annotations

import random
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

# Each situation ties a Korean/English listening context to a plausible
# genre family and target audience, so combinations stay realistic instead
# of mixing unrelated genres into one niche.
SITUATIONS = [
    {
        "tag_ko": "새벽 코딩",
        "situation_ko": "새벽에 코딩할 때 듣는",
        "situation_en": "late-night coding sessions",
        "audience": "개발자 / 심야에 집중해서 작업하는 사람들",
        "genre": "Lo-fi Jazz",
        "sub_genre": "Piano & Rhodes Lo-fi",
        "visual_theme": "어두운 방, 모니터 불빛, 창밖 새벽 풍경",
        "bpm_range": (60, 80),
    },
    {
        "tag_ko": "비 오는 카페 작업",
        "situation_ko": "비 오는 날 카페에서 작업할 때 듣는",
        "situation_en": "working in a cafe on a rainy day",
        "audience": "카페에서 노트북으로 작업/공부하는 사람들",
        "genre": "Jazz Hop",
        "sub_genre": "Rainy Cafe Jazz",
        "visual_theme": "비 오는 창가, 따뜻한 조명의 카페, 커피잔",
        "bpm_range": (70, 90),
    },
    {
        "tag_ko": "몽환적인 게임 배경음",
        "situation_ko": "몽환적인 분위기의 게임을 할 때 듣는",
        "situation_en": "playing dreamy, atmospheric games",
        "audience": "인디 게임 / 탐험형 게임을 즐기는 사람들",
        "genre": "Ambient",
        "sub_genre": "Dreamy Game Ambient",
        "visual_theme": "안개 낀 숲, 흐릿한 빛 입자, 몽환적 색감",
        "bpm_range": (55, 75),
    },
    {
        "tag_ko": "늦은 밤 홀로 작업",
        "situation_ko": "늦은 밤 혼자 작업할 때 듣는",
        "situation_en": "working alone late at night",
        "audience": "야근/사이드 프로젝트를 하는 직장인",
        "genre": "Downtempo",
        "sub_genre": "Late Night Downtempo",
        "visual_theme": "홀로 켜진 스탠드 조명, 도시 야경",
        "bpm_range": (65, 85),
    },
    {
        "tag_ko": "도서관 공부",
        "situation_ko": "도서관에서 공부할 때 듣는",
        "situation_en": "studying in a quiet library",
        "audience": "수험생 / 시험 준비생",
        "genre": "Lo-fi Hip Hop",
        "sub_genre": "Study Lo-fi",
        "visual_theme": "조용한 도서관, 책상 위 스탠드, 창가 햇살",
        "bpm_range": (70, 90),
    },
    {
        "tag_ko": "저녁 휴식",
        "situation_ko": "감성적인 저녁 시간에 휴식할 때 듣는",
        "situation_en": "unwinding in the evening",
        "audience": "하루를 마무리하며 쉬고 싶은 사람들",
        "genre": "Neo-classical",
        "sub_genre": "Emotional Piano",
        "visual_theme": "노을빛 창가, 그랜드 피아노, 따뜻한 색감",
        "bpm_range": (55, 70),
    },
    {
        "tag_ko": "일요일 브런치",
        "situation_ko": "일요일 아침 여유로운 브런치 시간에 듣는",
        "situation_en": "a relaxed Sunday morning brunch",
        "audience": "느긋한 주말 아침을 보내는 사람들",
        "genre": "Jazz",
        "sub_genre": "Sunday Morning Jazz",
        "visual_theme": "햇살 드는 부엌, 커피와 빵, 따뜻한 톤",
        "bpm_range": (85, 105),
    },
    {
        "tag_ko": "눈 오는 겨울밤",
        "situation_ko": "눈 오는 겨울밤 창밖을 보며 듣는",
        "situation_en": "watching snow fall on a winter night",
        "audience": "겨울 감성을 좋아하는 사람들",
        "genre": "Ambient",
        "sub_genre": "Winter Ambient",
        "visual_theme": "눈 내리는 창밖, 벽난로, 차분한 조명",
        "bpm_range": (50, 70),
    },
    {
        "tag_ko": "심야 드라이브",
        "situation_ko": "장시간 운전할 때 차분하게 듣는",
        "situation_en": "long, calm night drives",
        "audience": "밤에 운전하는 사람들",
        "genre": "Chillhop",
        "sub_genre": "Night Drive Chillhop",
        "visual_theme": "도심 야경, 빗물 맺힌 창문, 가로등 불빛",
        "bpm_range": (75, 95),
    },
    {
        "tag_ko": "독서 시간",
        "situation_ko": "독서에 몰입할 때 듣는",
        "situation_en": "deep reading sessions",
        "audience": "책을 오래 읽는 사람들",
        "genre": "Neo-classical",
        "sub_genre": "Reading Ambience",
        "visual_theme": "서재, 따뜻한 스탠드 조명, 쌓인 책",
        "bpm_range": (55, 75),
    },
    {
        "tag_ko": "명상/반신욕",
        "situation_ko": "명상하거나 반신욕할 때 듣는",
        "situation_en": "meditation and relaxation time",
        "audience": "명상/휴식이 필요한 사람들",
        "genre": "Ambient",
        "sub_genre": "Meditation Ambient",
        "visual_theme": "은은한 촛불, 잔잔한 물결, 어두운 톤",
        "bpm_range": (45, 65),
    },
    {
        "tag_ko": "주말 창작 시간",
        "situation_ko": "주말 오후 그림을 그리거나 만들기를 할 때 듣는",
        "situation_en": "weekend afternoon creative crafting",
        "audience": "그림/공예 등 창작 활동을 하는 사람들",
        "genre": "Lo-fi Jazz",
        "sub_genre": "Creative Focus Lo-fi",
        "visual_theme": "작업대 위 물감과 도구, 자연광",
        "bpm_range": (70, 88),
    },
]

MOODS = ["차분한", "몽환적인", "따뜻한", "잔잔한", "약간 신비로운", "포근한", "느긋한"]

INSTRUMENT_POOL = [
    "Rhodes piano", "upright piano", "soft synth pad", "brushed drums",
    "warm bass", "vinyl crackle", "muted guitar", "ambient strings",
    "light saxophone", "rainfall texture", "soft vibraphone",
]

PLAYLIST_LENGTHS = [30, 60, 90, 120]

NEGATIVE_PROMPT = (
    "No named real-world artists or existing song titles/melodies. "
    "Avoid sudden loud transients, harsh clipping, or abrupt silence."
)


class MockAiProvider(AiProvider):
    name = "mock"

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def _usage(self) -> AiUsage:
        return AiUsage(provider=self.name, model="mock-v1", input_tokens=0, output_tokens=0, estimated_cost_usd=0.0)

    def generate_concepts(self, channel_context: dict, count: int) -> tuple[list[ConceptCandidate], AiUsage]:
        pairs = [(s, m) for s in SITUATIONS for m in MOODS]
        insights = channel_context.get("performance_insights") or {}
        preferred_genres = set(insights.get("recommended_genres") or [])
        preferred_moods = set(insights.get("recommended_moods") or [])

        if preferred_genres or preferred_moods:
            # Bias toward what performed well, but cap it well under 100% so
            # the batch still explores fresh combinations - spec section 17
            # explicitly warns against just re-running past winners.
            preferred = [p for p in pairs if p[0]["genre"] in preferred_genres or p[1] in preferred_moods]
            other = [p for p in pairs if p not in preferred]
            self._rng.shuffle(preferred)
            self._rng.shuffle(other)
            bias_count = min(len(preferred), max(1, round(count * 0.4)))
            chosen = preferred[:bias_count] + other[: count - bias_count]
            self._rng.shuffle(chosen)
        else:
            self._rng.shuffle(pairs)
            chosen = pairs[:count]

        candidates: list[ConceptCandidate] = []
        for situation, mood in chosen:
            length_min = self._rng.choice(PLAYLIST_LENGTHS)
            concept_name = f"{mood} {situation['tag_ko']} | {situation_label(situation)}"
            keywords = [
                situation["sub_genre"].lower(),
                situation["genre"].lower(),
                mood,
                "vocal-less",
                "playlist",
            ]
            description = (
                f"{situation['situation_ko']} {mood} {situation['genre']} 플레이리스트. "
                f"타깃: {situation['audience']}. 보컬 없이 {length_min}분 내외로 이어지는 "
                f"배경음악으로, {situation['visual_theme']} 분위기의 영상과 함께 제공된다."
            )
            candidates.append(
                ConceptCandidate(
                    concept_name=concept_name,
                    target_audience=situation["audience"],
                    listening_situation=situation["situation_ko"] + " (" + situation["situation_en"] + ")",
                    genre=situation["genre"],
                    sub_genre=situation["sub_genre"],
                    mood=mood,
                    visual_theme=situation["visual_theme"],
                    keywords=keywords,
                    estimated_playlist_length_min=length_min,
                    description=description,
                )
            )
        return candidates, self._usage()

    def evaluate_concepts(self, concepts: list[ConceptCandidate]) -> tuple[list[ConceptEvaluation], AiUsage]:
        evaluations: list[ConceptEvaluation] = []
        seen_names = set()

        for idx, c in enumerate(concepts):
            breakdown = {
                "situation_clarity": _score_text_specificity(c.listening_situation),
                "target_audience_clarity": _score_text_specificity(c.target_audience),
                "long_listen_justification": 8.0 if c.estimated_playlist_length_min >= 60 else 6.0,
                "differentiation": 10.0 if c.concept_name not in seen_names else 3.0,
                "branding_visual_ease": _score_text_specificity(c.visual_theme),
                "seriesability": 7.5 if len(c.keywords) >= 4 else 5.0,
                "genre_mood_focus": 9.0 if c.genre and c.mood and "," not in c.genre else 5.0,
            }
            seen_names.add(c.concept_name)

            weights_sum = sum(breakdown.values())
            total_score = round((weights_sum / (len(breakdown) * 10)) * 100, 1)

            reasoning = (
                f"'{c.listening_situation}' 상황이 구체적이며 타깃({c.target_audience})이 명확함. "
                f"장르/분위기가 {c.genre}/{c.mood}로 좁게 정의되어 브랜딩하기 쉬움. "
                f"{'길이가 60분 이상이라 롱리슨 근거가 충분함.' if c.estimated_playlist_length_min >= 60 else '길이가 짧아 롱리슨 근거는 보통 수준.'}"
            )

            evaluations.append(
                ConceptEvaluation(
                    concept_index=idx,
                    total_score=total_score,
                    breakdown=breakdown,
                    reasoning=reasoning,
                )
            )
        return evaluations, self._usage()

    def generate_music_prompts(self, concept: ConceptCandidate, count: int) -> tuple[list[MusicPromptSpec], AiUsage]:
        situation = next(
            (s for s in SITUATIONS if s["genre"] == concept.genre and s["sub_genre"] == concept.sub_genre),
            SITUATIONS[0],
        )
        bpm_lo, bpm_hi = situation["bpm_range"]

        specs: list[MusicPromptSpec] = []
        structures = [
            "intro (short) - main theme A - variation B - main theme A' - gentle outro",
            "ambient intro - looped groove core - subtle build - fade outro",
            "soft intro - theme - bridge - theme reprise - fade",
        ]
        energies = ["low", "low-medium", "medium"]

        for i in range(count):
            bpm = self._rng.randint(bpm_lo, bpm_hi)
            instruments = self._rng.sample(INSTRUMENT_POOL, k=4)
            specs.append(
                MusicPromptSpec(
                    title_hint=f"{concept.concept_name} - Track {i + 1}",
                    genre=concept.genre,
                    sub_genre=concept.sub_genre,
                    mood=concept.mood,
                    bpm=bpm,
                    tempo="slow" if bpm < 80 else "mid-tempo",
                    instruments=instruments,
                    energy_level=self._rng.choice(energies),
                    song_structure=self._rng.choice(structures),
                    production_style="warm, analog-leaning, minimal dynamic range for background listening",
                    vocal=False,
                    duration_target_sec=self._rng.choice([180, 210, 240]),
                    loopability="high - clean loop point at phrase boundary",
                    negative_prompt=NEGATIVE_PROMPT,
                )
            )
        return specs, self._usage()

    def generate_youtube_titles(self, concept: ConceptCandidate, count: int = 5) -> tuple[list[str], AiUsage]:
        situation_ko = concept.listening_situation.split(" (")[0]
        situation_en = concept.listening_situation.split("(")[-1].rstrip(")").strip().title()
        emoji = _pick_emoji(concept)
        primary_audience = concept.target_audience.split(" /")[0]

        candidates = [
            f"{situation_ko} | {concept.mood} {concept.sub_genre} 플레이리스트",
            f"{situation_en} {emoji} {concept.sub_genre} for {primary_audience}",
            f"{emoji} {situation_ko} {concept.sub_genre} BGM",
            f"{concept.mood} {concept.genre} Mix — {situation_en}",
            f"{primary_audience} 추천 | {situation_ko} 음악",
        ]
        return candidates[:count], self._usage()

    def generate_description(
        self, concept: ConceptCandidate, chosen_title: str, playlist_duration_min: int
    ) -> tuple[YoutubeDescriptionSpec, AiUsage]:
        situation_ko = concept.listening_situation.split(" (")[0]
        situation_core = situation_ko.rsplit(" 듣는", 1)[0]  # strip the trailing verb so it reads naturally mid-sentence
        description = (
            f"{situation_core} 어울리는 {concept.mood} {concept.sub_genre} 모음입니다.\n\n"
            f"{concept.target_audience}을(를) 위해 만들었으며, 보컬 없이 약 {playlist_duration_min}분간 "
            f"이어집니다. {situation_ko} 상황에 맞춰 편하게 틀어두세요.\n\n"
            "비슷한 분위기의 플레이리스트를 계속 올릴 예정이니 채널을 구독해주세요."
        )
        genre_tag = "#" + concept.genre.replace(" ", "").replace("-", "")
        sub_genre_tag = "#" + concept.sub_genre.replace(" ", "").replace("-", "")
        hashtags = [sub_genre_tag, genre_tag, "#playlist", "#studymusic" if "공부" in situation_ko or "study" in situation_ko.lower() else "#bgm"]
        keywords = list(dict.fromkeys([*concept.keywords, concept.target_audience, concept.mood]))

        spec = YoutubeDescriptionSpec(
            description=description,
            hashtags=hashtags,
            keywords=keywords,
            playlist_category="Music",
            thumbnail_text=chosen_title.split("|")[0].strip()[:40],
        )
        return spec, self._usage()

    def generate_thumbnail_prompt(self, concept: ConceptCandidate, theme: dict) -> tuple[str, AiUsage]:
        situation_ko = concept.listening_situation.split(" (")[0]
        prompt = (
            f"{theme.get('visual_style')} thumbnail. Environment: {theme.get('environment')}. "
            f"Lighting: {theme.get('lighting')}. Camera: {theme.get('camera_angle')}. "
            f"Mood: {concept.mood} {concept.genre}, evoking '{situation_ko}'. "
            f"Main subject: {theme.get('main_character')}. Text overlay style: {theme.get('text_style')}. "
            "No real-world brand logos, no named real people, no existing copyrighted characters."
        )
        return prompt, self._usage()

    def analyze_performance(
        self, top_records: list[VideoPerformanceRecord], all_records: list[VideoPerformanceRecord]
    ) -> tuple[PerformanceInsights, AiUsage]:
        if not top_records:
            insights = PerformanceInsights(
                summary="아직 축적된 성과 데이터가 없어 채널 니치 설정만으로 콘셉트를 생성합니다.",
                recommended_situations=[],
                recommended_genres=[],
                recommended_moods=[],
                bpm_min=None,
                bpm_max=None,
                title_structure_notes="",
                thumbnail_style_notes="",
                video_length_minutes_recommendation=None,
                things_to_avoid_repeating="",
            )
            return insights, self._usage()

        situations = [r.listening_situation.split(" (")[0] for r in top_records]
        genres = [r.genre for r in top_records]
        moods = [r.mood for r in top_records]

        def top_n(items: list[str], n: int = 3) -> list[str]:
            counts: dict[str, int] = {}
            for item in items:
                counts[item] = counts.get(item, 0) + 1
            return [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]]

        all_bpms = [bpm for r in top_records for bpm in r.bpm_values]
        bpm_min = min(all_bpms) if all_bpms else None
        bpm_max = max(all_bpms) if all_bpms else None

        lengths = sorted(r.video_length_min for r in top_records if r.video_length_min)
        length_reco = round(lengths[len(lengths) // 2]) if lengths else None

        top_titles = [r.chosen_title for r in top_records[:3]]

        summary = (
            f"최근 성과 상위 {len(top_records)}개 영상(전체 {len(all_records)}개 중) 분석 결과, "
            f"'{', '.join(top_n(situations, 2))}' 계열 상황과 '{', '.join(top_n(genres, 2))}' 장르, "
            f"'{', '.join(top_n(moods, 2))}' 분위기에서 시청 지속률/CTR/구독 전환이 상대적으로 높았습니다."
        )

        insights = PerformanceInsights(
            summary=summary,
            recommended_situations=top_n(situations),
            recommended_genres=top_n(genres),
            recommended_moods=top_n(moods),
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            title_structure_notes=(
                "성과 좋은 제목들의 공통 구조: 사용 상황 설명 + 장르/분위기 키워드 조합. "
                "아래는 참고용 예시일 뿐 그대로 재사용하지 말 것: " + "; ".join(top_titles)
            ),
            thumbnail_style_notes="기존 채널 ThumbnailTheme을 유지하되, 상위 콘텐츠와 유사한 색감/분위기 톤을 우선 고려.",
            video_length_minutes_recommendation=length_reco,
            things_to_avoid_repeating=(
                "동일한 콘셉트명, 제목 문구, 썸네일 텍스트를 그대로 반복하지 말 것. "
                "상황/장르/분위기 조합 패턴만 참고하고 세부 표현은 새로 변형할 것."
            ),
        )
        return insights, self._usage()


def _pick_emoji(concept: ConceptCandidate) -> str:
    haystack = (concept.listening_situation + " " + concept.sub_genre).lower()
    emoji_map = [
        ("rain", "☔"), ("비", "☔"),
        ("snow", "❄️"), ("눈", "❄️"),
        ("coding", "💻"), ("코딩", "💻"),
        ("drive", "🚗"), ("운전", "🚗"),
        ("night", "🌙"), ("밤", "🌙"),
        ("study", "📚"), ("공부", "📚"),
        ("game", "🎮"), ("게임", "🎮"),
        ("brunch", "☕"), ("브런치", "☕"),
        ("reading", "📖"), ("독서", "📖"),
        ("meditation", "🕯️"), ("명상", "🕯️"),
    ]
    for keyword, emoji in emoji_map:
        if keyword in haystack:
            return emoji
    return "🎧"


def _score_text_specificity(text: str) -> float:
    if not text:
        return 2.0
    length = len(text.strip())
    if length < 6:
        return 4.0
    if length < 15:
        return 7.0
    return 9.0


def situation_label(situation: dict) -> str:
    return situation["sub_genre"]
