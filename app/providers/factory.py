from ..config import settings
from .base import AiProvider
from .claude_provider import ClaudeAiProvider
from .mock_provider import MockAiProvider


def get_ai_provider() -> AiProvider:
    if settings.ai_provider == "claude":
        return ClaudeAiProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    return MockAiProvider()
