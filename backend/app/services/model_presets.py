"""主流聊天模型的可安装预设。

目录依据 models.dev（MIT，https://models.dev）公开维护的模型能力信息整理；
Base URL 以各供应商的 OpenAI Chat Completions / Responses / Anthropic Messages 官方接口为准。这里刻意只
收录当前应用两种客户端协议可以实际调用的聊天模型，向量、语音、图像模型不在此列。

``thinking_config`` 是发送给模型 SDK 的请求参数映射：
``enabled`` / ``disabled`` 用于思考开关，``efforts`` 的键用于思考强度。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.token_budgets import DEFAULT_TOOL_RESULT_MAX_TOKENS

CATALOG_SOURCE = "models.dev 开源模型目录（https://models.dev）"
OFFICIAL_DEEPSEEK_OPENAI_BASE_URL = "https://api.deepseek.com/v1"
SCNET_OPENAI_BASE_URL = "https://api.scnet.cn/api/llm/v1"

# 模型发现协议与聊天协议并不完全相同。预设显式标记发现适配器，避免把所有厂商都假定为
# Bearer + /models：Gemini 的原生列表接口使用 x-goog-api-key 且响应为 models[]，
# Anthropic 使用 x-api-key / anthropic-version，其他预设采用各自 OpenAI 兼容或 Responses 端点。
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
# 各家的 Claude Code 兼容网关只实现 /v1/messages，不提供 /v1/models（阿里云文档明确
# 写了这一点）。显式标记为不支持，避免发一次注定 404 的请求后把配置问题报成密钥问题。
UNSUPPORTED_DISCOVERY = {"adapter": "unsupported", "reason": "该端点仅提供 /v1/messages，不支持模型列表查询"}
# 方舟 Agent Plan / Coding Plan 的套餐网关支持与 OpenAI 兼容的 ``GET /models``；
# 该接口会按套餐和当前账号返回实际可用的模型，不能用普通方舟的 ``/endpoints`` 代替。
VOLCENGINE_ARK_PLAN_DISCOVERY = {
    "adapter": "openai_compatible",
    "path": "/models",
    "response_key": "data",
}

# Anthropic 协议的凭证头在各网关之间不一致：官方与 DeepSeek 接受 x-api-key，而
# 阿里云 / 智谱 / Kimi 的文档只给出 ANTHROPIC_AUTH_TOKEN（Claude Code 将其发为
# Authorization: Bearer）。预设据此声明，客户端按声明发送对应请求头。
AUTH_STYLE_API_KEY = "x-api-key"
AUTH_STYLE_BEARER = "bearer"


def recommended_tool_preview_tokens(input_budget_tokens: int) -> int:
    """Match mainstream Agent preview sizes while keeping full results retrievable."""
    budget = max(1, int(input_budget_tokens))
    if budget < 65_536:
        target = DEFAULT_TOOL_RESULT_MAX_TOKENS
    elif budget <= 262_144:
        target = 12_288
    else:
        target = 16_384
    return min(budget, target)


def _openai_reasoning_config() -> dict[str, Any]:
    return {
        "enabled": {"reasoning_effort": "medium"},
        "disabled": {"reasoning_effort": "none"},
        "efforts": {
            "minimal": {"reasoning_effort": "minimal"},
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
            "max": {"reasoning_effort": "max"},
        },
    }


def _anthropic_thinking_config() -> dict[str, Any]:
    """Return Anthropic Messages settings for adaptive-thinking Claude models.

    This is deliberately different from OpenAI's ``reasoning_effort``.
    ``ChatAnthropic`` serializes ``effort`` into ``output_config.effort``.
    """
    efforts = ("low", "medium", "high", "xhigh", "max")
    return {
        "enabled": {"thinking": {"type": "adaptive"}, "effort": "medium"},
        "disabled": {},
        "efforts": {
            effort: {"thinking": {"type": "adaptive"}, "effort": effort}
            for effort in efforts
        },
    }


def anthropic_adaptive_thinking_config(
    efforts: list[str] | None = None, default_effort: str | None = None
) -> dict[str, Any]:
    """Build a native Anthropic thinking mapping, optionally narrowed by effort."""
    supported = ("low", "medium", "high", "xhigh", "max")
    selected = [effort for effort in (efforts or list(supported)) if effort in supported]
    if not selected:
        selected = list(supported)
    if default_effort in supported and default_effort not in selected:
        selected.append(default_effort)
    resolved_default_effort = (
        default_effort
        if default_effort in selected
        else ("medium" if "medium" in selected else selected[0])
    )
    return {
        "enabled": {"thinking": {"type": "adaptive"}, "effort": resolved_default_effort},
        "disabled": {},
        "efforts": {
            effort: {"thinking": {"type": "adaptive"}, "effort": effort}
            for effort in selected
        },
    }


def _toggle_config(key: str = "enable_thinking") -> dict[str, Any]:
    return {"enabled": {key: True}, "disabled": {key: False}}


def _deepseek_thinking_config() -> dict[str, Any]:
    return {"enabled": {"thinking": {"type": "enabled"}}, "disabled": {"thinking": {"type": "disabled"}}}


def official_deepseek_thinking_config() -> dict[str, Any]:
    """Return a fresh native thinking mapping for the official OpenAI endpoint."""
    return deepcopy(_deepseek_thinking_config())


def is_official_deepseek_openai_endpoint(base_url: str) -> bool:
    return str(base_url or "").rstrip("/").lower() == OFFICIAL_DEEPSEEK_OPENAI_BASE_URL


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
            "tool_result_max_tokens": recommended_tool_preview_tokens(24_576),
            "is_multimodal": False,
        }
        for model_name, display_name, thinking_config in items
    ]


def _coding_models(
    *items: tuple[str, str, int, int, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """按显式上下文/输出容量构造 coding plan 模型条目。

    ``_models()`` 的 32768 默认值对编码套餐是错的量级：这些端点主打长上下文，套用默认
    值会在管理端看不出异常的情况下把可用窗口砍掉一个数量级。这里要求每条显式给出容量，
    并按既有约定推导压缩阈值与单次工具结果预览上限。
    """
    entries: list[dict[str, Any]] = []
    for model_name, display_name, context_window, max_output, thinking_config in items:
        threshold = context_window - max_output
        entries.append(
            {
                "model_name": model_name,
                "display_name": display_name,
                "thinking_config": deepcopy(thinking_config or {}),
                "context_window_tokens": context_window,
                "context_compaction_threshold_tokens": threshold,
                "max_output_tokens": max_output,
                "tool_result_max_tokens": recommended_tool_preview_tokens(threshold),
                "is_multimodal": False,
            }
        )
    return entries


def _volcengine_plan_reasoning_config() -> dict[str, Any]:
    """Return the documented Responses reasoning-effort mapping for Ark plans."""
    return {
        "enabled": {"reasoning_effort": "medium"},
        "disabled": {"reasoning_effort": "none"},
        "efforts": {
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
        },
    }


def _gemini_25_thinking_config() -> dict[str, Any]:
    """Native Gemini 2.5 thinking budgets (``-1`` means dynamic)."""
    return {
        "enabled": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": -1}},
        "disabled": {"thinkingConfig": {"includeThoughts": False, "thinkingBudget": 0}},
        "efforts": {
            "minimal": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 512}},
            "low": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 1024}},
            "medium": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 4096}},
            "high": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 8192}},
            "max": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": -1}},
        },
    }


def _gemini_3_thinking_config() -> dict[str, Any]:
    """Native Gemini 3 thinking levels; Gemini 3 cannot disable thinking."""
    return {
        "enabled": {"thinkingConfig": {"includeThoughts": True, "thinkingLevel": "high"}},
        "efforts": {
            "low": {"thinkingConfig": {"includeThoughts": True, "thinkingLevel": "low"}},
            "high": {"thinkingConfig": {"includeThoughts": True, "thinkingLevel": "high"}},
        },
    }


def _gemini_models(*items: tuple[str, str, dict[str, Any], bool]) -> list[dict[str, Any]]:
    entries = _models(*[(name, display, config) for name, display, config, _ in items])
    for entry, (_, _, _, multimodal) in zip(entries, items):
        entry["context_window_tokens"] = 1_000_000
        entry["context_compaction_threshold_tokens"] = 991_808
        entry["max_output_tokens"] = 8_192
        entry["tool_result_max_tokens"] = recommended_tool_preview_tokens(991_808)
        entry["is_multimodal"] = multimodal
        entry["supports_disabled_thinking"] = "disabled" in entry["thinking_config"]
    return entries


def _volcengine_plan_models(
    *items: tuple[str, str, int, int, bool, bool, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Build Ark subscription-plan models from the official OpenCode limits.

    The plan docs provide operational limits for the Responses and Chat API
    configurations. They are lower than a few models' theoretical maximum
    output, leaving a usable input budget for this application's Agent loop.
    """
    entries = _coding_models(
        *(
            (model_name, display_name, context_window, max_output, thinking_config)
            for model_name, display_name, context_window, max_output, _, _, thinking_config in items
        )
    )
    for entry, (_, _, _, _, is_multimodal, supports_disabled_thinking, _) in zip(entries, items):
        entry["is_multimodal"] = is_multimodal
        entry["supports_disabled_thinking"] = supports_disabled_thinking
    return entries


def _glm_thinking_config() -> dict[str, Any]:
    return {
        "enabled": {"thinking": {"type": "enabled"}},
        "disabled": {"thinking": {"type": "disabled"}},
    }


def _scnet_reasoning_config() -> dict[str, Any]:
    """Return a DeepSeek V4 mapping valid for SCNet Chat and Responses APIs.

    SCNet documents ``reasoning_effort`` as ``high``/``max`` for Chat
    Completions, while ``none`` is only documented by Responses.  Use the
    cross-protocol ``enable_thinking`` switch for the disabled state so the
    preset remains usable when the installer overrides the protocol.
    """
    return {
        "enabled": {"reasoning_effort": "high"},
        "disabled": {"enable_thinking": False},
        "efforts": {
            "high": {"reasoning_effort": "high"},
            "max": {"reasoning_effort": "max"},
        },
    }


def _scnet_models() -> list[dict[str, Any]]:
    """Build the current SCNet model catalogue used by API and Token Plan keys.

    SCNet keeps the same model IDs behind its regular and subscription keys;
    the key determines billing and entitlement.  The list is intentionally
    also used as a discovery fallback so a Token Plan can be configured before
    its account-specific ``/models`` response is available.
    """
    entries = _models(
        ("GLM-5.2", "GLM-5.2", None),
        ("GLM-5", "GLM-5", None),
        ("GLM-5.1", "GLM-5.1", None),
        ("Kimi-K3", "Kimi K3", None),
        ("Kimi-K2.7-Code", "Kimi K2.7 Code", None),
        ("Kimi-K2.6", "Kimi K2.6", None),
        ("Kimi-K2.5", "Kimi K2.5", None),
        ("DeepSeek-V4-Flash", "DeepSeek V4 Flash", _scnet_reasoning_config()),
        ("DeepSeek-V3.2", "DeepSeek V3.2", None),
        ("MiniMax-M3", "MiniMax M3", None),
        ("MiniMax-M2.7", "MiniMax M2.7", None),
        ("MiniMax-M2.5", "MiniMax M2.5", None),
        ("MiMo-V2.5-Pro", "MiMo V2.5 Pro", None),
    )
    for entry in entries:
        entry["is_multimodal"] = entry["model_name"] in {"Kimi-K2.6", "Kimi-K2.5"}
    return entries


def _scnet_coding_models() -> list[dict[str, Any]]:
    """Build SCNet Coding Plan's currently published model catalogue."""
    return _models(
        ("MiniMax-M2.5", "MiniMax M2.5", None),
        ("Qwen3-235B-A22B", "Qwen3 235B A22B", _toggle_config()),
    )


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
        "id": "openai_responses",
        "name": "OpenAI Responses API",
        "provider_type": "openai_responses",
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
        "base_url": OFFICIAL_DEEPSEEK_OPENAI_BASE_URL,
        "api_key_hint": "sk-...",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        # DeepSeek 会频繁切换正式模型与别名；创建时应通过 /models 获取当前账号可用模型，
        # 不在预设界面展示容易过时的 deepseek-chat / deepseek-reasoner 固定条目。
        "thinking_config": _deepseek_thinking_config(),
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
        "id": "scnet",
        "name": "国家超算互联网（SCNet）",
        "provider_type": "openai_compatible",
        "base_url": SCNET_OPENAI_BASE_URL,
        "api_key_hint": "sk-...",
        "api_key_prefix": "sk-",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _scnet_models(),
    },
    {
        # Token Plan uses the same gateway and model IDs as the regular API,
        # but the subscription key (sk-tp-...) must be kept separate.  Responses
        # is the native agent-friendly OpenAI protocol; installation can still
        # override this to openai_compatible for /chat/completions tools.
        "id": "scnet_token_plan",
        "name": "国家超算互联网 · Token Plan（Responses API）",
        "provider_type": "openai_responses",
        "base_url": SCNET_OPENAI_BASE_URL,
        "api_key_hint": "sk-tp-...（Token Plan 专属）",
        "api_key_prefix": "sk-tp-",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _scnet_models(),
    },
    {
        # Coding Plan uses a separate subscription key (sk-sp-...) and a
        # smaller, coding-focused model catalogue than Token Plan.
        "id": "scnet_coding_plan",
        "name": "国家超算互联网 · Coding Plan（Responses API）",
        "provider_type": "openai_responses",
        "base_url": SCNET_OPENAI_BASE_URL,
        "api_key_hint": "sk-sp-...（Coding Plan 专属）",
        "api_key_prefix": "sk-sp-",
        "model_discovery": OPENAI_COMPATIBLE_DISCOVERY,
        "models": _scnet_coding_models(),
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
        # 方舟官方将此套餐命名为 Agent Plan；它是普通方舟 /api/v3 Endpoint
        # 推理之外的专属套餐，不可混用 API Key 或 Base URL。
        "id": "volcengine_ark_agent_plan",
        "name": "火山方舟 · Agent Plan（Responses API）",
        "provider_type": "openai_responses",
        "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
        "api_key_hint": "套餐专属 API Key",
        "model_discovery": VOLCENGINE_ARK_PLAN_DISCOVERY,
        "models": _volcengine_plan_models(
            (
                "ark-code-latest", "Ark Code Latest", 256_000, 32_000, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-2.1-turbo", "Doubao Seed 2.1 Turbo", 256_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-evolving", "Doubao Seed Evolving", 1_024_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "glm-5.3", "GLM-5.3", 1_024_000, 65_536, False, False,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "glm-latest", "GLM Latest", 1_024_000, 65_536, False, False,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "deepseek-v4-flash", "DeepSeek V4 Flash", 1_024_000, 65_536, False, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "deepseek-v4-pro", "DeepSeek V4 Pro", 1_024_000, 65_536, False, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-2.0-lite", "Doubao Seed 2.0 Lite", 256_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-2.0-mini", "Doubao Seed 2.0 Mini", 256_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "minimax-m3", "MiniMax M3", 1_024_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            ("kimi-k2.7-code", "Kimi K2.7 Code", 256_000, 32_000, True, True, None),
            (
                "kimi-k3", "Kimi K3", 1_024_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
        ),
    },
    {
        "id": "volcengine_ark_coding_plan",
        "name": "火山方舟 · Coding Plan（Responses API）",
        "provider_type": "openai_responses",
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "api_key_hint": "套餐专属 API Key",
        "model_discovery": VOLCENGINE_ARK_PLAN_DISCOVERY,
        "models": _volcengine_plan_models(
            (
                "ark-code-latest", "Ark Code Latest", 256_000, 32_000, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-2.1-turbo", "Doubao Seed 2.1 Turbo", 256_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "glm-5.3", "GLM-5.3", 1_024_000, 65_536, False, False,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "glm-latest", "GLM Latest", 1_024_000, 65_536, False, False,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "deepseek-v4-flash", "DeepSeek V4 Flash", 1_024_000, 65_536, False, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "deepseek-v4-pro", "DeepSeek V4 Pro", 1_024_000, 65_536, False, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "doubao-seed-2.0-lite", "Doubao Seed 2.0 Lite", 256_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            (
                "minimax-m3", "MiniMax M3", 1_024_000, 65_536, True, True,
                _volcengine_plan_reasoning_config(),
            ),
            ("kimi-k2.7-code", "Kimi K2.7 Code", 256_000, 32_000, True, True, None),
        ),
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
        "name": "Google Gemini（原生 API）",
        "provider_type": "gemini_native",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_hint": "AIza...",
        "model_discovery": GEMINI_DISCOVERY,
        "models": _gemini_models(
            ("gemini-2.5-pro", "Gemini 2.5 Pro", _gemini_25_thinking_config(), True),
            ("gemini-2.5-flash", "Gemini 2.5 Flash", _gemini_25_thinking_config(), True),
            ("gemini-3-pro-preview", "Gemini 3 Pro Preview", _gemini_3_thinking_config(), True),
            ("gemini-3-flash-preview", "Gemini 3 Flash Preview", _gemini_3_thinking_config(), True),
        ),
    },
    # ---------------------------------------------------------------------
    # 国内云厂商的 Anthropic 兼容套餐端点（Token Plan / Coding Plan）
    #
    # 这些端点复用 Anthropic Messages 协议，因此走 provider_type="anthropic"，
    # AnthropicClient 无需改动即可请求 {base_url}/v1/messages。三点与官方 Anthropic 不同：
    #   1. 认证头：阿里云 / 智谱 / Kimi 文档给的是 ANTHROPIC_AUTH_TOKEN（对应 Bearer），
    #      仅 DeepSeek 明确写了 x-api-key「Fully Supported」。故用 auth_style 区分。
    #   2. base_url 已包含各家的网关前缀（/apps/anthropic、/api/anthropic、/anthropic），
    #      不要再补 /v1，客户端会自行拼接 /v1/messages。
    #   3. 模型列表接口大多不存在，必须写死 models，否则发现失败时会退化成
    #      「请检查 API Key」这种把配置问题误报成密钥问题的提示。
    #
    # 容量取值原则：只有厂商文档明确写出的上下文才写进预设（[1m] 后缀 = 1M 窗口，
    # kimi-k2.7-code = 256K）。max_output 属于本产品自选的保守预算而非厂商声明值，
    # 管理端可上调。文档未给出容量的模型 ID 见各条目下方注释，不进预设以免写入错误量级。
    # ---------------------------------------------------------------------
    {
        "id": "aliyun_bailian_coding_plan",
        "name": "阿里云百炼 · Coding Plan（Anthropic 兼容）",
        "provider_type": "anthropic",
        "base_url": "https://coding.dashscope.aliyuncs.com/apps/anthropic",
        "api_key_hint": "sk-...",
        "auth_style": AUTH_STYLE_BEARER,
        # 文档明确说明该端点只提供 /v1/messages，不提供 /v1/models。
        "model_discovery": UNSUPPORTED_DISCOVERY,
        "models": _coding_models(
            ("qwen3.7-plus[1m]", "Qwen3.7 Plus（1M 上下文）", 1_000_000, 65_536, None),
        ),
    },
    {
        "id": "aliyun_bailian_token_plan",
        "name": "阿里云百炼 · Token Plan（Anthropic 兼容）",
        "provider_type": "anthropic",
        "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        "api_key_hint": "sk-...",
        "auth_style": AUTH_STYLE_BEARER,
        "model_discovery": UNSUPPORTED_DISCOVERY,
        # 该套餐还列出 qwen3.8-max-preview / qwen3.7-max / qwen3.6-flash / glm-5.2，
        # 但文档未给出各自的上下文窗口，需要时在模型编辑里按实际容量手动添加。
        "models": _coding_models(
            ("qwen3.7-plus[1m]", "Qwen3.7 Plus（1M 上下文）", 1_000_000, 65_536, None),
            ("deepseek-v4-pro", "DeepSeek V4 Pro", 1_000_000, 384_000, None),
        ),
    },
    {
        "id": "zhipu_coding_plan",
        "name": "智谱 GLM Coding Plan（Anthropic 兼容）",
        "provider_type": "anthropic",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_key_hint": "...",
        "auth_style": AUTH_STYLE_BEARER,
        "models": _coding_models(
            ("glm-5.2[1m]", "GLM-5.2（1M 上下文）", 1_000_000, 65_536, _glm_thinking_config()),
        )
        # glm-4.7 在该端点可用，但这一页没有给出窗口，沿用目录中既有的保守默认值。
        + _models(("glm-4.7", "GLM-4.7", _glm_thinking_config())),
    },
    {
        "id": "moonshot_anthropic",
        "name": "Moonshot Kimi（Anthropic 兼容）",
        "provider_type": "anthropic",
        "base_url": "https://api.moonshot.cn/anthropic",
        "api_key_hint": "sk-...",
        "auth_style": AUTH_STYLE_BEARER,
        # kimi-k2.7-code-highspeed / kimi-k2.6 也可用，文档未给出窗口，故未纳入。
        "models": _coding_models(
            ("kimi-k3[1m]", "Kimi K3（1M 上下文）", 1_000_000, 65_536, None),
            ("kimi-k2.7-code", "Kimi K2.7 Code（256K）", 262_144, 32_768, None),
        ),
    },
    {
        "id": "deepseek_anthropic",
        "name": "DeepSeek（Anthropic 兼容）",
        "provider_type": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_hint": "sk-...",
        # 唯一明确记录 x-api-key「Fully Supported」的一家，沿用默认认证头。
        "auth_style": AUTH_STYLE_API_KEY,
        "models": _coding_models(
            ("deepseek-v4-pro", "DeepSeek V4 Pro", 1_000_000, 384_000, None),
            ("deepseek-v4-flash", "DeepSeek V4 Flash", 1_000_000, 384_000, None),
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
    # These IDs are returned by OpenAI-compatible /models endpoints without
    # capacity metadata. Keep the documented limits here so discovery does not
    # silently collapse a long-context model to the 32K fallback. The dated
    # DashScope ID is the pinned alias of qwen3.7-max used by existing users.
    "qwen3.7-max": {
        "display_name": "Qwen3.7 Max",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 65_536,
        "tool_result_max_tokens": 4_096,
    },
    "qwen3.7-max-2026-06-08": {
        "display_name": "Qwen3.7 Max",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 65_536,
        "tool_result_max_tokens": 4_096,
    },
    "kimi-k2.7-code": {
        "display_name": "Kimi K2.7 Code",
        "context_window_tokens": 262_144,
        "max_output_tokens": 32_768,
        "tool_result_max_tokens": 4_096,
    },
    "glm-5.2": {
        "display_name": "GLM-5.2",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 131_072,
        "tool_result_max_tokens": 4_096,
    },
    "qwen3.8-max-preview": {
        "display_name": "Qwen3.8 Max Preview",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 131_072,
        "tool_result_max_tokens": 4_096,
    },
}

for capability in DISCOVERED_MODEL_CAPABILITIES.values():
    capability["context_compaction_threshold_tokens"] = (
        capability["context_window_tokens"] - capability["max_output_tokens"]
    )
    capability["tool_result_max_tokens"] = recommended_tool_preview_tokens(
        capability["context_compaction_threshold_tokens"]
    )


def list_provider_presets() -> list[dict[str, Any]]:
    """返回可安全暴露给管理前端的预设副本。"""
    return deepcopy(PROVIDER_PRESETS)


def get_provider_preset(preset_id: str) -> dict[str, Any] | None:
    for preset in PROVIDER_PRESETS:
        if preset["id"] == preset_id:
            return deepcopy(preset)
    return None


def find_provider_preset(
    base_url: str,
    provider_type: str,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Find a preset, using the credential prefix when gateways are shared.

    SCNet's regular API, Token Plan and Coding Plan intentionally share both
    the gateway URL and (for two plans) the protocol.  The persisted provider
    record has no preset ID, so a supplied API key is the only reliable way to
    select the right fallback catalogue.
    """
    normalized = base_url.rstrip("/").lower()
    base_matches = [
        preset
        for preset in PROVIDER_PRESETS
        if preset["base_url"].rstrip("/").lower() == normalized
    ]
    if api_key:
        specific_matches = [
            preset
            for preset in base_matches
            if str(preset.get("api_key_prefix") or "") not in {"", "sk-"}
            and api_key.startswith(str(preset["api_key_prefix"]))
        ]
        if specific_matches:
            return deepcopy(specific_matches[0])
        generic_matches = [
            preset
            for preset in base_matches
            if str(preset.get("api_key_prefix") or "") == "sk-"
            and api_key.startswith("sk-")
        ]
        if generic_matches:
            return deepcopy(generic_matches[0])
    matches = [preset for preset in base_matches if preset["provider_type"] == provider_type]
    if api_key and len(matches) > 1:
        for preset in matches:
            prefix = str(preset.get("api_key_prefix") or "")
            if prefix and api_key.startswith(prefix):
                # The generic ``sk-`` prefix also matches plan keys; prefer
                # the plan-specific prefixes when more than one is present.
                if prefix != "sk-" or not any(
                    str(candidate.get("api_key_prefix") or "") != "sk-"
                    and api_key.startswith(str(candidate.get("api_key_prefix") or ""))
                    for candidate in matches
                ):
                    return deepcopy(preset)
    if matches:
        return deepcopy(matches[0])
    return None


def find_model_preset(model_name: str, provider_preset: dict[str, Any] | None = None) -> dict[str, Any] | None:
    candidates = [provider_preset] if provider_preset else PROVIDER_PRESETS
    normalized = model_name.lower()
    capability = DISCOVERED_MODEL_CAPABILITIES.get(normalized)
    for preset in candidates:
        if not preset:
            continue
        for model in preset["models"]:
            if model["model_name"].lower() == normalized:
                result = deepcopy(model)
                # The global capability catalogue is authoritative for
                # provider-agnostic discovery. Keep provider-specific preset
                # values intact because a plan endpoint may document a
                # different operational limit for the same model ID.
                if capability is not None and provider_preset is None:
                    result.update(deepcopy(capability))
                return result
    return deepcopy(capability) if capability else None


def resolve_auth_style(base_url: str, provider_type: str) -> str:
    """按已保存的 base_url 反查该网关要求的 Anthropic 凭证头形式。

    供应商表只存 base_url + 加密密钥，没有认证方式字段，因此这里复用
    ``find_provider_preset`` 的匹配方式（``discover_models`` 已是同一套做法），
    避免为一个由 base_url 完全决定的属性增加数据库迁移。未命中预设时返回官方
    Anthropic 的 x-api-key，与改动前的行为一致。
    """
    preset = find_provider_preset(base_url, provider_type)
    if preset and preset.get("auth_style") == AUTH_STYLE_BEARER:
        return AUTH_STYLE_BEARER
    return AUTH_STYLE_API_KEY


def thinking_efforts(thinking_config: dict[str, Any]) -> list[str]:
    efforts = thinking_config.get("efforts") if isinstance(thinking_config, dict) else None
    return list(efforts.keys()) if isinstance(efforts, dict) else []
