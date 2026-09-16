import shutil
from pathlib import Path

from .base import GeneratedAudio, MusicGenerationProvider


class ManualUploadProvider(MusicGenerationProvider):
    """The Phase 2 MVP path: a human generates audio elsewhere (Suno's web
    app, or anything else) and uploads the file through the admin UI. This
    provider doesn't call any external API — it just registers where the
    uploaded file landed, so the rest of the pipeline (quality analysis,
    playlist assembly) doesn't need to know or care how the audio was
    sourced."""

    name = "manual"

    def is_automatic(self) -> bool:
        return False

    def save_uploaded_file(self, source_path: Path, storage_dir: Path, track_id: int) -> str:
        storage_dir.mkdir(parents=True, exist_ok=True)
        ext = source_path.suffix or ".wav"
        dest = storage_dir / f"track_{track_id}{ext}"
        shutil.copy(source_path, dest)
        return str(dest)
