from app.core.crypto import decrypt_secret
from app.models.ai_provider import AIProvider, ProviderType
from app.services.ai_client.anthropic import AnthropicClient
from app.services.ai_client.gemini_native import GeminiNativeClient
from app.services.ai_client.base import AIClient
from app.services.ai_client.openai_compatible import OpenAICompatibleClient
from app.services.ai_client.openai_responses import OpenAIResponsesClient
from app.services.model_presets import resolve_auth_style


def build_ai_client(provider: AIProvider) -> AIClient:
    api_key = decrypt_secret(provider.api_key_encrypted)
    if provider.provider_type == ProviderType.ANTHROPIC:
        # 国内各家 Claude Code 兼容网关的凭证头不统一，按 base_url 命中的预设决定。
        return AnthropicClient(
            provider.base_url,
            api_key,
            auth_style=resolve_auth_style(provider.base_url, provider.provider_type.value),
        )
    if provider.provider_type == ProviderType.GEMINI_NATIVE:
        return GeminiNativeClient(provider.base_url, api_key)
    if provider.provider_type == ProviderType.OPENAI_RESPONSES:
        return OpenAIResponsesClient(provider.base_url, api_key)
    return OpenAICompatibleClient(provider.base_url, api_key)
