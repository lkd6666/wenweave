from app.core.crypto import decrypt_secret
from app.models.ai_provider import AIProvider, ProviderType
from app.services.ai_client.anthropic import AnthropicClient
from app.services.ai_client.base import AIClient
from app.services.ai_client.openai_compatible import OpenAICompatibleClient


def build_ai_client(provider: AIProvider) -> AIClient:
    api_key = decrypt_secret(provider.api_key_encrypted)
    if provider.provider_type == ProviderType.ANTHROPIC:
        return AnthropicClient(provider.base_url, api_key)
    return OpenAICompatibleClient(provider.base_url, api_key)
