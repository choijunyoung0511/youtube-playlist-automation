from .base import MusicGenerationProvider
from .future_provider import FutureProvider
from .manual_provider import ManualUploadProvider
from .suno_provider import SunoProvider


def get_music_generation_provider(name: str = "manual") -> MusicGenerationProvider:
    if name == "suno":
        return SunoProvider()
    if name == "future":
        return FutureProvider()
    return ManualUploadProvider()
