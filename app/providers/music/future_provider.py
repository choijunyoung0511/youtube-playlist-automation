from pathlib import Path

from ..types import MusicPromptSpec
from .base import GeneratedAudio, MusicGenerationProvider


class FutureProvider(MusicGenerationProvider):
    """Placeholder seam for a future official music-generation API
    (Suno once it ships one, or a different vendor). Registered now so
    MUSIC_GENERATION_PROVIDER=future is a valid config value ahead of an
    actual implementation."""

    name = "future"

    def is_automatic(self) -> bool:
        return True

    def generate(self, prompt: MusicPromptSpec, output_dir: Path) -> GeneratedAudio:
        raise NotImplementedError("No automatic music-generation provider is wired up yet.")
