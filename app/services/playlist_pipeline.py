"""Orchestrates the Phase 3 pipeline: order+fill SELECTED tracks into a
Playlist, assemble the crossfaded audio, and render the background video.
Shared by the admin route and the Phase 3 test/scripts so the two never
drift apart.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Concept, Playlist, PlaylistStatus
from .audio_assembly_service import assemble_playlist_audio
from .playlist_service import PlaylistService
from .video_service import compose_video, generate_background_image, generate_particle_overlay


def build_and_render_playlist(
    db: Session,
    concept: Concept,
    audio_dir: Path,
    video_dir: Path,
    target_length_min: int = 60,
    target_duration_sec: int | None = None,
    crossfade_sec: int = 3,
) -> Playlist:
    playlist = PlaylistService(db).build_playlist(
        concept, target_length_min=target_length_min, target_duration_sec=target_duration_sec
    )

    audio_out = audio_dir / f"playlist_{playlist.id}.wav"
    duration_sec = assemble_playlist_audio(playlist, audio_out, crossfade_sec=crossfade_sec)

    bg_image = video_dir / f"playlist_{playlist.id}_bg.png"
    particle_overlay = video_dir / f"playlist_{playlist.id}_particles.mp4"
    video_out = video_dir / f"playlist_{playlist.id}.mp4"

    generate_background_image(concept.mood, bg_image)
    generate_particle_overlay(concept.mood, particle_overlay)
    compose_video(bg_image, particle_overlay, audio_out, playlist.title, video_out, duration_sec)

    playlist.audio_path = str(audio_out)
    playlist.video_path = str(video_out)
    playlist.duration_sec = int(duration_sec)
    playlist.status = PlaylistStatus.READY
    db.commit()
    db.refresh(playlist)
    return playlist
