"""MusicGenerationProvider: abstracts *how audio actually gets produced*
from a MusicPromptSpec (spec section 7).

This is deliberately a separate interface from AiProvider — AiProvider only
ever produces text/JSON (concepts, prompts, evaluations); a
MusicGenerationProvider is responsible for turning a MusicPromptSpec into an
audio file on disk, whether that happens by calling an API or by a human
manually uploading a file generated elsewhere.

As of Phase 2, Suno has no official public generation API, so
SunoProvider.generate() raises NotImplementedError and points callers at
the manual upload workflow. When Suno (or another vendor) ships an official
API, only a new provider class needs to be added — nothing else in the
pipeline references Suno directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..types import MusicPromptSpec


@dataclass
class GeneratedAudio:
    audio_path: str
    duration_sec: float
    source_provider: str


class MusicGenerationProvider(ABC):
    name: str

    @abstractmethod
    def is_automatic(self) -> bool:
        """True if generate() can produce audio without a human in the loop."""

    def generate(self, prompt: MusicPromptSpec, output_dir: Path) -> GeneratedAudio:
        raise NotImplementedError(
            f"{self.name} does not support automatic generation; "
            "use the manual upload workflow instead."
        )
