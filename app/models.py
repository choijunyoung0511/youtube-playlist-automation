import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from .database import Base


class ConceptStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    EVALUATED = "EVALUATED"
    SELECTED = "SELECTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TrackStatus(str, enum.Enum):
    GENERATED = "GENERATED"
    ANALYZING = "ANALYZING"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"
    PLAYLIST_READY = "PLAYLIST_READY"


class PlaylistStatus(str, enum.Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"  # added for Phase 4's admin Reject button (spec section 14); not in the original enum list
    UPLOADED = "UPLOADED"


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    niche = Column(String, nullable=False)
    description = Column(Text)
    visual_theme = Column(Text)
    youtube_playlist_id = Column(String, nullable=True)  # optional real YouTube playlist new uploads get added to
    created_at = Column(DateTime, default=datetime.utcnow)

    concepts = relationship("Concept", back_populates="channel")


class ThumbnailTheme(Base):
    """One brand kit per channel (spec section 11) - reused for every
    playlist's thumbnail prompt so the channel looks consistent instead of
    each thumbnail inventing its own look."""

    __tablename__ = "thumbnail_themes"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), unique=True, nullable=False)

    visual_style = Column(String, default="soft cinematic lo-fi illustration")
    main_character = Column(String, default="none (empty cozy room / landscape only)")
    environment = Column(String, default="warm, low-light interior or rainy window view")
    lighting = Column(String, default="warm lamp light with cool blue shadows")
    camera_angle = Column(String, default="eye-level, slightly wide")
    text_style = Column(String, default="clean sans-serif, bottom-left, high contrast")

    created_at = Column(DateTime, default=datetime.utcnow)

    channel = relationship("Channel")


class Concept(Base):
    __tablename__ = "concepts"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)

    concept_name = Column(String, nullable=False)
    target_audience = Column(String)
    listening_situation = Column(String)
    genre = Column(String)
    sub_genre = Column(String)
    mood = Column(String)
    visual_theme = Column(String)
    keywords = Column(JSON)  # list[str]
    estimated_playlist_length_min = Column(Integer)
    description = Column(Text)

    status = Column(SAEnum(ConceptStatus, native_enum=False), default=ConceptStatus.DRAFT, nullable=False)
    evaluation_score = Column(Float)
    evaluation_breakdown = Column(JSON)  # dict[str, float]
    evaluation_reasoning = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    channel = relationship("Channel", back_populates="concepts")
    tracks = relationship("Track", back_populates="concept", cascade="all, delete-orphan")
    playlist = relationship("Playlist", back_populates="concept", uselist=False, cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=False)

    title = Column(String)
    prompt = Column(JSON)  # full MusicPromptSpec, serialized
    generation_provider = Column(String, default="manual", nullable=False)  # which MusicGenerationProvider sourced the audio
    audio_path = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    bpm = Column(Integer, nullable=True)

    quality_status = Column(SAEnum(TrackStatus, native_enum=False), default=TrackStatus.GENERATED, nullable=False)
    quality_reason = Column(Text, nullable=True)
    analysis_data = Column(JSON, nullable=True)  # raw librosa/ffmpeg metrics behind quality_reason

    created_at = Column(DateTime, default=datetime.utcnow)

    concept = relationship("Concept", back_populates="tracks")
    playlist_links = relationship("PlaylistTrack", back_populates="track", cascade="all, delete-orphan")


class Playlist(Base):
    """A playlist is authored from one originating Concept (concept_id), but its
    actual song lineup is the many-to-many PlaylistTrack join below — so a strong
    track can be reused in a later playlist (e.g. a "best of" or remix edition)
    without being duplicated as a row."""

    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id"), unique=True, nullable=False)

    title = Column(String)
    target_length_min = Column(Integer, default=60)  # 30/60/90/120 per spec section 9
    duration_sec = Column(Integer)
    audio_path = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    thumbnail_path = Column(String, nullable=True)
    thumbnail_prompt = Column(Text, nullable=True)

    # YouTube metadata (spec sections 12-13) - generated once the playlist
    # asset (audio+video) is READY, reviewed by a human before upload.
    title_candidates = Column(JSON, nullable=True)  # list[str], 5 AI-generated options
    chosen_title = Column(String, nullable=True)  # which candidate the admin picked
    youtube_description = Column(Text, nullable=True)
    hashtags = Column(JSON, nullable=True)  # list[str]
    keywords = Column(JSON, nullable=True)  # list[str]
    playlist_category = Column(String, nullable=True)
    thumbnail_text = Column(String, nullable=True)

    status = Column(SAEnum(PlaylistStatus, native_enum=False), default=PlaylistStatus.BUILDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    concept = relationship("Concept", back_populates="playlist")
    youtube_video = relationship("YoutubeVideo", back_populates="playlist", uselist=False, cascade="all, delete-orphan")
    track_links = relationship(
        "PlaylistTrack",
        back_populates="playlist",
        order_by="PlaylistTrack.position",
        cascade="all, delete-orphan",
    )


class PlaylistTrack(Base):
    """Ordered many-to-many join between Playlist and Track (spec section 9:
    ordering by BPM/energy/mood requires an explicit position, and section
    9/23's reuse question requires a Track not to belong to a single Playlist).

    The unique constraint is on (playlist_id, position), not
    (playlist_id, track_id): filling a 60-120 minute playlist from a
    handful of SELECTED tracks means deliberately repeating the same
    track at multiple positions within one playlist (see
    playlist_service.build_sequence) - it's cross-playlist accidental
    duplication that would be the actual bug, and nothing here prevents
    a track from also appearing in a different playlist."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (UniqueConstraint("playlist_id", "position", name="uq_playlist_position"),)

    id = Column(Integer, primary_key=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=False)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False)
    position = Column(Integer, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)

    playlist = relationship("Playlist", back_populates="track_links")
    track = relationship("Track", back_populates="playlist_links")


class YoutubeVideo(Base):
    __tablename__ = "youtube_videos"

    id = Column(Integer, primary_key=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), unique=True, nullable=False)

    youtube_video_id = Column(String)
    title = Column(String)
    published_at = Column(DateTime, nullable=True)

    playlist = relationship("Playlist", back_populates="youtube_video")
    stats = relationship("YoutubeStats", back_populates="video", cascade="all, delete-orphan")


class YoutubeStats(Base):
    """One row per (video, day). The unique constraint makes daily stats collection
    idempotent (re-running the same day's pull upserts instead of duplicating), and
    the date index keeps date-range/cumulative rollups (spec section 16-17) cheap
    even as videos and days accumulate across multiple channels."""

    __tablename__ = "youtube_video_stats"
    __table_args__ = (
        UniqueConstraint("youtube_video_id", "date", name="uq_video_date"),
        Index("ix_youtube_video_stats_date", "date"),
    )

    id = Column(Integer, primary_key=True)
    youtube_video_id = Column(Integer, ForeignKey("youtube_videos.id"), nullable=False)

    date = Column(DateTime)
    views = Column(Integer)
    watch_time_min = Column(Float)
    average_view_duration_sec = Column(Float)
    average_percentage_viewed = Column(Float)
    impressions = Column(Integer)
    ctr = Column(Float)
    likes = Column(Integer)
    comments = Column(Integer)
    subscribers_gained = Column(Integer)

    video = relationship("YoutubeVideo", back_populates="stats")


class ContentStrategy(Base):
    """The latest performance-derived content strategy per channel (spec
    section 17) - recomputed on demand from accumulated YoutubeStats, not
    accumulated indefinitely: each refresh replaces the previous one."""

    __tablename__ = "content_strategies"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), unique=True, nullable=False)

    summary = Column(Text)
    recommended_situations = Column(JSON)  # list[str]
    recommended_genres = Column(JSON)  # list[str]
    recommended_moods = Column(JSON)  # list[str]
    bpm_min = Column(Integer, nullable=True)
    bpm_max = Column(Integer, nullable=True)
    title_structure_notes = Column(Text)
    thumbnail_style_notes = Column(Text)
    video_length_minutes_recommendation = Column(Integer, nullable=True)
    things_to_avoid_repeating = Column(Text)

    based_on_video_count = Column(Integer, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)

    channel = relationship("Channel")


class AiCostLog(Base):
    """Tracks every AI call so per-content and monthly cost can be computed (spec section 22)."""

    __tablename__ = "ai_cost_logs"

    id = Column(Integer, primary_key=True)
    provider = Column(String, index=True)
    model = Column(String, index=True)
    request_type = Column(String, index=True)  # generate_concepts, evaluate_concepts, generate_music_prompts, ...
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
