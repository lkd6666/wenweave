"""主流聊天模型的可安装预设。

目录依据 models.dev（MIT，https://models.dev）公开维护的模型能力信息整理；
Base URL 以各供应商的 OpenAI 兼容 / Anthropic Messages 官方接口为准。这里刻意只
收录当前应用两种客户端协议可以实际调用的聊天模型，向量、语音、图像模型不在此列。

``thinking_config`` 是发送给模型 SDK 的请求参数映射：
``enabled`` / ``disabled`` 用于思考开关，``efforts`` 的键用于思考强度。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

CATALOG_SOURCE = "models.dev 开源模型目录（https://models.dev）"

# 模型发现协议与聊天协议并不完全相同。预设显式标记发现适配器，避免把所有厂商都假定为
# Bearer + /models：Gemini 的原生列表接口使用 x-goog-api-key 且响应为 models[]，
# Anthropic 使用 x-api-key / anthropic-version，其他预设采用各自 OpenAI 兼容端点。
OPENAI_COMPATIBLE_DISCOVERY = {"adapter": "openai_compatible", "path": "/models", "response_key": "data"}
ANTHROPIC_DISCOVERY = {"adapter": "anthropic", "path": "/v1/models", "response_key": "data"}
GEMINI_DISCOVERY = {
    "adapter": "gemini_native",
    "url": "https://generativelanguage.googleapis.com/v1beta/models",
    "response_key": "models",
    "strip_prefix": "models/",
}
VOLCENGINE_ARK_DISCOVERY = {
    "adapter": "volcengine_ark",
    "path": "/endpoints",
    "response_key": "items",
}


def _openai_reasoning_config() -> dict[str, Any]:
    return {
        "enabled": {"reasoning_effort": "medium"},
        "disabled": {"reasoning_effort": "none"},
        "efforts": {
            "minimal": {"reasoning_effort": "minimal"},
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
        },
    }


def _anthropic_thinking_config() -> dict[str, Any]:
    return {
        "enabled": {"thinking": {"type": "enabled", "budget_tokens": 4096}},
        "disabled": {},
        "efforts": {
            "low": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
            "medium": {"thinking": {"type": "enabled", "budget_tokens": 4096}},
            "high": {"thinking": {"type": "enabled", "budget_tokens": 8192}},
        },
    }


def _toggle_config(key: str = "enable_thinking") -> dict[str, Any]:
    return {"enabled": {key: True}, "disabled": {key: False}}


def _models(*items: tuple[str, str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    return [
        {
            "model_name": model_name,
            "display_name": display_name,
            "thinking_config": deepcopy(thinking_config or {}),
            # Unknown discovered models use the same conservative value. The
            # admin UI exposes an override when a provider documents another
            # limit.
            "context_window_tokens": 32768,
            "context_compaction_threshold_tokens": 24576,
            "max_output_tokens": 8192,
            "tool_result_max_tokens": 4096,
        }
        for model_name, display_name, thinking_config in items
    ]


# ``id`` 是稳定的产品内部标识，不依赖某个供应商模型名称。后续增加模型不影响已有配置。
PROVIDER_PRESETS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "name": "OpenAI",
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("gpt-5", "GPT-5", _openai_reasoning_config()),
            ("gpt-5-mini", "GPT-5 mini", _openai_reasoning_config()),
            ("o3", "o3", _openai_reasoning_config()),
            ("gpt-4.1", "GPT-4.1", None),
            ("gpt-4o", "GPT-4o", None),
        ),
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key_hint": "sk-ant-...",
        "model_discovery": ANTHROPIC_DISCOVERY,
        "models": _models(
            ("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5", _anthropic_thinking_config()),
            ("claude-opus-4-5-20251101", "Claude Opus 4.5", _anthropic_thinking_config()),
            ("claude-haiku-4-5-20251001", "Claude Haiku 4.5", _anthropic_thinking_config()),
        ),
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "provider_type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        # DeepSeek 会频繁切换正式模型与别名；创建时应通过 /models 获取当前账号可用模型，
        # 不在预设界面展示容易过时的 deepseek-chat / deepseek-reasoner 固定条目。
        "models": [],
    },
    {
        "id": "qwen",
        "name": "阿里云百炼 / 通义千问",
        "provider_type": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("qwen-max", "Qwen Max", None),
            ("qwen-plus", "Qwen Plus", None),
            ("qwen3-235b-a22b", "Qwen3 235B", _toggle_config()),
            ("qwen3-32b", "Qwen3 32B", _toggle_config()),
        ),
    },
    {
        "id": "volcengine_ark",
        "name": "火山引擎 / 方舟",
        "provider_type": "openai_compatible",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_hint": "...",
        # 方舟调用时的 model 是用户创建的推理 Endpoint ID（ep-...），不是公共模型名。
        "model_discovery": VOLCENGINE_ARK_DISCOVERY,
        "models": [],
    },
    {
        "id": "baidu_qianfan",
        "name": "百度智能云 / 千帆（文心）",
        "provider_type": "openai_compatible",
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_key_hint": "bce-v3/...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        # 千帆可用模型随账号权限和区域变化，必须通过 V2 models 接口即时获取。
        "models": [],
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "provider_type": "openai_compatible",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("kimi-k2.5", "Kimi K2.5", _toggle_config()),
            ("kimi-k2-thinking", "Kimi K2 Thinking", None),
            ("kimi-k2-0905-preview", "Kimi K2", None),
        ),
    },
    {
        "id": "zhipu",
        "name": "智谱 AI / GLM",
        "provider_type": "openai_compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_hint": "...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("glm-4.7", "GLM-4.7", {"enabled": {"thinking": {"type": "enabled"}}, "disabled": {"thinking": {"type": "disabled"}}}),
            ("glm-4.5", "GLM-4.5", {"enabled": {"thinking": {"type": "enabled"}}, "disabled": {"thinking": {"type": "disabled"}}}),
            ("glm-4.5-air", "GLM-4.5-Air", {"enabled": {"thinking": {"type": "enabled"}}, "disabled": {"thinking": {"type": "disabled"}}}),
        ),
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "provider_type": "openai_compatible",
        "base_url": "https://api.siliconflow.com/v1",
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("Qwen/Qwen3-235B-A22B", "Qwen3 235B（硅基流动）", _toggle_config()),
            ("deepseek-ai/DeepSeek-R1", "DeepSeek R1（硅基流动）", None),
            ("moonshotai/Kimi-K2.5", "Kimi K2.5（硅基流动）", None),
        ),
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "provider_type": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_hint": "sk-or-v1-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("openai/gpt-5", "GPT-5（OpenRouter）", {"enabled": {"reasoning": {"effort": "medium"}}, "disabled": {"reasoning": {"effort": "none"}}, "efforts": {"low": {"reasoning": {"effort": "low"}}, "medium": {"reasoning": {"effort": "medium"}}, "high": {"reasoning": {"effort": "high"}}}}),
            ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5（OpenRouter）", None),
            ("deepseek/deepseek-r1", "DeepSeek R1（OpenRouter）", None),
        ),
    },
    {
        "id": "groq",
        "name": "Groq",
        "provider_type": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_hint": "gsk_...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("llama-3.3-70b-versatile", "Llama 3.3 70B", None),
            ("qwen/qwen3-32b", "Qwen3 32B（Groq）", _toggle_config()),
            ("openai/gpt-oss-120b", "GPT-OSS 120B（Groq）", _openai_reasoning_config()),
        ),
    },
    {
        "id": "together",
        "name": "Together AI",
        "provider_type": "openai_compatible",
        "base_url": "https://api.together.xyz/v1",
        "api_key_hint": "...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B", None),
            ("Qwen/Qwen3-235B-A22B-fp8-tput", "Qwen3 235B", _toggle_config()),
            ("deepseek-ai/DeepSeek-R1", "DeepSeek R1", None),
        ),
    },
    {
        "id": "xai",
        "name": "xAI / Grok",
        "provider_type": "openai_compatible",
        "base_url": "https://api.x.ai/v1",
        "api_key_hint": "xai-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("grok-4", "Grok 4", _openai_reasoning_config()),
            ("grok-3-mini", "Grok 3 Mini", _openai_reasoning_config()),
            ("grok-3", "Grok 3", None),
        ),
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "provider_type": "openai_compatible",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_hint": "...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("mistral-large-latest", "Mistral Large", None),
            ("codestral-latest", "Codestral", None),
            ("magistral-medium-latest", "Magistral Medium", _openai_reasoning_config()),
        ),
    },
    {
        "id": "perplexity",
        "name": "Perplexity",
        "provider_type": "openai_compatible",
        "base_url": "https://api.perplexity.ai",
        "api_key_hint": "pplx-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _models(
            ("sonar", "Sonar", None),
            ("sonar-pro", "Sonar Pro", None),
            ("sonar-reasoning-pro", "Sonar Reasoning Pro", _openai_reasoning_config()),
        ),
    },
    {
        "id": "gemini",
        "name": "Google Gemini（OpenAI 兼容）",
        "provider_type": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_hint": "AIza...",
        "model_discovery": GEMINI_DISCOVERY,
        "models": _models(
            ("gemini-2.5-pro", "Gemini 2.5 Pro", _openai_reasoning_config()),
            ("gemini-2.5-flash", "Gemini 2.5 Flash", _openai_reasoning_config()),
        ),
    },
]

# Capability records are deliberately separate from ``PROVIDER_PRESETS``.
# Some providers return current account model IDs through /models but omit
# token limits; adding those IDs to the installable preset list would make the
# list stale again.  The records below enrich a discovered model only.
DISCOVERED_MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "deepseek-v4-flash": {
        "display_name": "DeepSeek V4 Flash",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 384_000,
        "tool_result_max_tokens": 4_096,
    },
    "deepseek-v4-pro": {
        "display_name": "DeepSeek V4 Pro",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 384_000,
        "tool_result_max_tokens": 4_096,
    },
}

for capability in DISCOVERED_MODEL_CAPABILITIES.values():
    capability["context_compaction_threshold_tokens"] = (
        capability["context_window_tokens"] - capability["max_output_tokens"]
    )
    capability["tool_result_max_tokens"] = max(
        4_096,
        capability["context_compaction_threshold_tokens"] // 16,
    )


def list_provider_presets() -> list[dict[str, Any]]:
    """返回可安全暴露给管理前端的预设副本。"""
    return deepcopy(PROVIDER_PRESETS)


def get_provider_preset(preset_id: str) -> dict[str, Any] | None:
    for preset in PROVIDER_PRESETS:
        if preset["id"] == preset_id:
            return deepcopy(preset)
    return None


def find_provider_preset(base_url: str, provider_type: str) -> dict[str, Any] | None:
    normalized = base_url.rstrip("/").lower()
    for preset in PROVIDER_PRESETS:
        if preset["provider_type"] == provider_type and preset["base_url"].rstrip("/").lower() == normalized:
            return deepcopy(preset)
    return None


def find_model_preset(model_name: str, provider_preset: dict[str, Any] | None = None) -> dict[str, Any] | None:
    candidates = [provider_preset] if provider_preset else PROVIDER_PRESETS
    normalized = model_name.lower()
    for preset in candidates:
        if not preset:
            continue
        for model in preset["models"]:
            if model["model_name"].lower() == normalized:
                return deepcopy(model)
    capability = DISCOVERED_MODEL_CAPABILITIES.get(normalized)
    return deepcopy(capability) if capability else None


def thinking_efforts(thinking_config: dict[str, Any]) -> list[str]:
    efforts = thinking_config.get("efforts") if isinstance(thinking_config, dict) else None
    return list(efforts.keys()) if isinstance(efforts, dict) else []
