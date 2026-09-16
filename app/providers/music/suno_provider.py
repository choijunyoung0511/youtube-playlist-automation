from pathlib import Path

from ..types import MusicPromptSpec
from .base import GeneratedAudio, MusicGenerationProvider


class SunoProvider(MusicGenerationProvider):
    """Suno has no official public API for programmatic generation as of
    this writing. Automating against Suno's consumer web app (browser
    automation, reverse-engineered endpoints, etc.) risks account
    suspension and is out of scope per spec section 7 — this provider
    exists only as the documented seam for when/if Suno ships an official
    API, and always raises until then."""

    name = "suno"

    def is_automatic(self) -> bool:
        return False

    def generate(self, prompt: MusicPromptSpec, output_dir: Path) -> GeneratedAudio:
        raise NotImplementedError(
            "Suno has no official generation API yet. Copy the prompt text "
            "(see MusicPromptSpec) into Suno manually, download the result, "
            "and upload it through ManualUploadProvider / the admin UI."
        )
