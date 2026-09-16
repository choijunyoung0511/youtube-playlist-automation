"""Generates the YouTube-facing metadata for a built Playlist (spec
sections 11-13) and moves it into REVIEW_REQUIRED for human approval."""

from pathlib import Path

from sqlalchemy.orm import Session

from ..models import AiCostLog, Concept, Playlist, PlaylistStatus, ThumbnailTheme
from ..providers.base import AiProvider
from ..providers.types import AiUsage, ConceptCandidate
from .thumbnail_service import render_thumbnail_image


def ensure_thumbnail_theme(db: Session, channel_id: int) -> ThumbnailTheme:
    theme = db.query(ThumbnailTheme).filter(ThumbnailTheme.channel_id == channel_id).first()
    if theme is None:
        theme = ThumbnailTheme(channel_id=channel_id)
        db.add(theme)
        db.commit()
        db.refresh(theme)
    return theme


def _to_candidate(concept: Concept) -> ConceptCandidate:
    return ConceptCandidate(
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


class YoutubeMetadataService:
    def __init__(self, db: Session, ai_provider: AiProvider):
        self.db = db
        self.ai = ai_provider

    def generate_titles(self, playlist: Playlist, count: int = 5) -> Playlist:
        concept = playlist.concept
        titles, usage = self.ai.generate_youtube_titles(_to_candidate(concept), count)
        self._log_cost(usage, "generate_youtube_titles", concept.id)

        playlist.title_candidates = titles
        if not playlist.chosen_title or playlist.chosen_title not in titles:
            playlist.chosen_title = titles[0]
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def choose_title(self, playlist: Playlist, title: str) -> Playlist:
        playlist.chosen_title = title
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def generate_description(self, playlist: Playlist) -> Playlist:
        concept = playlist.concept
        chosen_title = playlist.chosen_title or concept.concept_name
        spec, usage = self.ai.generate_description(_to_candidate(concept), chosen_title, playlist.target_length_min)
        self._log_cost(usage, "generate_description", concept.id)

        playlist.youtube_description = spec.description
        playlist.hashtags = spec.hashtags
        playlist.keywords = spec.keywords
        playlist.playlist_category = spec.playlist_category
        playlist.thumbnail_text = spec.thumbnail_text
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def generate_thumbnail(self, playlist: Playlist, thumbnail_dir: Path) -> Playlist:
        concept = playlist.concept
        theme = ensure_thumbnail_theme(self.db, concept.channel_id)
        theme_dict = {
            "visual_style": theme.visual_style,
            "main_character": theme.main_character,
            "environment": theme.environment,
            "lighting": theme.lighting,
            "camera_angle": theme.camera_angle,
            "text_style": theme.text_style,
        }
        prompt, usage = self.ai.generate_thumbnail_prompt(_to_candidate(concept), theme_dict)
        self._log_cost(usage, "generate_thumbnail_prompt", concept.id)

        text = playlist.thumbnail_text or playlist.chosen_title or concept.concept_name
        out_path = thumbnail_dir / f"playlist_{playlist.id}_thumb.png"
        render_thumbnail_image(concept.mood, text, out_path)

        playlist.thumbnail_prompt = prompt
        playlist.thumbnail_path = str(out_path)
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def generate_all(self, playlist: Playlist, thumbnail_dir: Path) -> Playlist:
        self.generate_titles(playlist)
        self.generate_description(playlist)
        self.generate_thumbnail(playlist, thumbnail_dir)

        playlist.status = PlaylistStatus.REVIEW_REQUIRED
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def _log_cost(self, usage: AiUsage, request_type: str, concept_id: int) -> None:
        log = AiCostLog(
            provider=usage.provider,
            model=usage.model,
            request_type=request_type,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
            concept_id=concept_id,
        )
        self.db.add(log)
        self.db.commit()
