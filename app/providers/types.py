from dataclasses import dataclass, field


@dataclass
class ConceptCandidate:
    concept_name: str
    target_audience: str
    listening_situation: str
    genre: str
    sub_genre: str
    mood: str
    visual_theme: str
    keywords: list[str]
    estimated_playlist_length_min: int
    description: str


@dataclass
class ConceptEvaluation:
    concept_index: int  # position in the candidate list this evaluation belongs to
    total_score: float  # 0-100
    breakdown: dict = field(default_factory=dict)  # criterion -> 0-10
    reasoning: str = ""


@dataclass
class MusicPromptSpec:
    title_hint: str
    genre: str
    sub_genre: str
    mood: str
    bpm: int
    tempo: str
    instruments: list[str]
    energy_level: str
    song_structure: str
    production_style: str
    vocal: bool
    duration_target_sec: int
    loopability: str
    negative_prompt: str


@dataclass
class AiUsage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class YoutubeDescriptionSpec:
    description: str
    hashtags: list[str]
    keywords: list[str]
    playlist_category: str
    thumbnail_text: str


@dataclass
class VideoPerformanceRecord:
    """One uploaded video's accumulated performance, joined with the
    content attributes that produced it - the input to analyze_performance()."""

    playlist_id: int
    concept_name: str
    listening_situation: str
    genre: str
    sub_genre: str
    mood: str
    target_audience: str
    bpm_values: list[int]
    video_length_min: float
    chosen_title: str
    thumbnail_text: str | None
    total_views: int
    total_watch_time_min: float
    avg_view_duration_sec: float
    avg_percentage_viewed: float
    avg_ctr: float
    total_likes: int
    total_comments: int
    total_subscribers_gained: int
    days_tracked: int
    score: float = 0.0


@dataclass
class PerformanceInsights:
    summary: str
    recommended_situations: list[str]
    recommended_genres: list[str]
    recommended_moods: list[str]
    bpm_min: int | None
    bpm_max: int | None
    title_structure_notes: str
    thumbnail_style_notes: str
    video_length_minutes_recommendation: int | None
    things_to_avoid_repeating: str
