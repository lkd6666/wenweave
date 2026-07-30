import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.models.ai_model import (
    AIModel,
    DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TOOL_RESULT_MAX_TOKENS,
)
from app.models.ai_provider import AIProvider
from app.models.user import User
from app.models.user_group import UserGroup
from app.schemas.ai_provider import (
    ModelBulkCreateRequest,
    ModelBulkCreateResult,
    ModelCreate,
    ModelDiscoveryItem,
    ModelDiscoveryResult,
    ModelRead,
    ModelUpdate,
    PresetDiscoveryRequest,
    PresetInstallRequest,
    ProviderPresetRead,
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
    TestConnectionRequest,
    TestConnectionResult,
)
from app.services.ai_client.factory import build_ai_client
from app.services.model_presets import (
    AUTH_STYLE_API_KEY,
    AUTH_STYLE_BEARER,
    CATALOG_SOURCE,
    find_model_preset,
    find_provider_preset,
    get_provider_preset,
    list_provider_presets,
    recommended_tool_preview_tokens,
    thinking_efforts,
    is_official_deepseek_openai_endpoint,
    official_deepseek_thinking_config,
)

router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"], dependencies=[Depends(require_admin)])


def _validate_model_budget(
    *,
    context_window_tokens: int,
    context_compaction_threshold_tokens: int,
    max_output_tokens: int,
    tool_result_max_tokens: int,
) -> None:
    """Validate the complete persisted budget, including PATCH combinations."""
    if context_compaction_threshold_tokens + max_output_tokens > context_window_tokens:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="压缩阈值与最大输出 token 之和不能超过模型最大上下文窗口",
        )
    if tool_result_max_tokens > context_compaction_threshold_tokens:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="单次工具返回 token 上限不能超过压缩阈值",
        )


def _effective_thinking_config(base_url: str, thinking_config: dict[str, Any] | None) -> dict[str, Any]:
    """Fill the documented native mapping only for unconfigured DeepSeek models."""
    if is_official_deepseek_openai_endpoint(base_url) and not thinking_config:
        return official_deepseek_thinking_config()
    return thinking_config or {}


def _to_provider_read(provider: AIProvider) -> ProviderRead:
    api_key_plain = decrypt_secret(provider.api_key_encrypted) if provider.api_key_encrypted else ""
    return ProviderRead(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key_masked=mask_secret(api_key_plain),
        models=[ModelRead.model_validate(m) for m in provider.models],
    )


def _validate_access_targets(
    db: Session, user_ids: list[int] | None, group_ids: list[int] | None
) -> tuple[list[User] | None, list[UserGroup] | None]:
    users: list[User] | None = None
    groups: list[UserGroup] | None = None
    if user_ids is not None:
        unique_user_ids = list(dict.fromkeys(user_ids))
        users = db.query(User).filter(User.id.in_(unique_user_ids)).all() if unique_user_ids else []
        if len(users) != len(unique_user_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户")
    if group_ids is not None:
        unique_group_ids = list(dict.fromkeys(group_ids))
        groups = db.query(UserGroup).filter(UserGroup.id.in_(unique_group_ids)).all() if unique_group_ids else []
        if len(groups) != len(unique_group_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在不存在的授权用户组")
    return users, groups


def _to_preset_read(preset: dict[str, Any]) -> ProviderPresetRead:
    return ProviderPresetRead(
        **{
            **preset,
            "models": [
                {**model, "thinking_efforts": thinking_efforts(model.get("thinking_config", {}))}
                for model in preset["models"]
            ],
        }
    )


def _metadata_integer(item: dict[str, Any], *paths: tuple[str, ...]) -> int | None:
    """Read vendor capacity fields without exposing vendor-specific payloads."""
    for path in paths:
        value: Any = item
        for key in path:
            if not isinstance(value, dict):
                break
            value = value.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _recommended_tool_result_max_tokens(context_threshold_tokens: int) -> int:
    """Recommend a model-visible preview cap; full output is stored separately."""
    return recommended_tool_preview_tokens(context_threshold_tokens)


def _discovery_token_budget(raw_model: dict[str, Any], known: dict[str, Any] | None) -> tuple[dict[str, int], str]:
    """Derive a valid Agent budget from public provider model metadata.

    OpenAI-compatible catalogues use several incompatible names.  We only
    accept explicit capacity fields.  A bare ``max_tokens`` is intentionally
    not treated as output capacity because many catalogues use it for the
    total context window.
    """
    reported_context = _metadata_integer(
        raw_model,
        ("context_length",),
        ("context_window",),
        ("context_window_tokens",),
        ("max_context_length",),
        ("input_token_limit",),
        ("inputTokenLimit",),
        ("limits", "context_length"),
        ("limits", "context_window"),
        ("architecture", "context_length"),
        ("top_provider", "context_length"),
    )
    reported_output = _metadata_integer(
        raw_model,
        ("max_output_tokens",),
        ("max_completion_tokens",),
        ("output_token_limit",),
        ("outputTokenLimit",),
        ("limits", "max_output_tokens"),
        ("limits", "output_token_limit"),
        ("architecture", "output_length"),
        ("top_provider", "max_completion_tokens"),
    )

    if reported_context and reported_context >= 8_192:
        context_window = min(reported_context, 2_000_000)
        context_source = "供应商接口"
    elif known:
        context_window = int(known.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS))
        context_source = "内置预设"
    else:
        context_window = DEFAULT_CONTEXT_WINDOW_TOKENS
        context_source = "保守默认值"

    preferred_output = (
        (reported_output or int(known.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)))
        if known
        else (reported_output or DEFAULT_MAX_OUTPUT_TOKENS)
    )
    # Retain at least the schema's minimum input threshold.  A provider may
    # advertise output equal to its full context, which is unusable for an
    # editing Agent that must send a system prompt and workspace map.
    output_ceiling = context_window - 1024
    # Without an explicit context field, a large output declaration cannot
    # prove the total window. Keep the default-window fallback usable instead
    # of assigning a 1k input budget from an ambiguous provider payload.
    if not reported_context and int(preferred_output) >= context_window:
        output_ceiling = min(output_ceiling, max(128, context_window // 4))
    max_output = min(max(128, int(preferred_output)), output_ceiling)
    threshold = context_window - max_output
    tool_limit = _recommended_tool_result_max_tokens(threshold)
    return (
        {
            "context_window_tokens": context_window,
            "context_compaction_threshold_tokens": threshold,
            "max_output_tokens": max_output,
            "tool_result_max_tokens": tool_limit,
        },
        context_source,
    )


def _model_discovery_item(
    model: dict[str, Any], provider_preset: dict[str, Any] | None, source: str
) -> ModelDiscoveryItem:
    model_name = str(model["model_name"])
    known = find_model_preset(model_name, provider_preset)
    if not known:
        known = find_model_preset(model_name)
    thinking_config = known.get("thinking_config", {}) if known else {}
    # The official DeepSeek OpenAI endpoint documents the native thinking.type
    # request shape even when its /models response contains no capability data.
    if is_official_deepseek_openai_endpoint(str((provider_preset or {}).get("base_url", ""))):
        thinking_config = official_deepseek_thinking_config()
    budget, context_window_source = _discovery_token_budget(model.get("metadata", {}), known)
    return ModelDiscoveryItem(
        model_name=model_name,
        display_name=known.get("display_name", model_name) if known else model_name,
        description=known.get("description", "") if known else "",
        **budget,
        thinking_config=thinking_config,
        supports_disabled_thinking=True,
        thinking_efforts=thinking_efforts(thinking_config),
        source=source,
        context_window_source=context_window_source,
    )


def _sync_default_discovered_budgets(
    db: Session, provider_id: int, discovered: list[ModelDiscoveryItem]
) -> int:
    """Refresh legacy conservative defaults without overwriting admin choices."""
    existing = {
        model.model_name: model
        for model in db.query(AIModel).filter(AIModel.provider_id == provider_id).all()
    }
    default_budget = (
        DEFAULT_CONTEXT_WINDOW_TOKENS,
        DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS,
        DEFAULT_MAX_OUTPUT_TOKENS,
        DEFAULT_TOOL_RESULT_MAX_TOKENS,
    )
    changed = 0
    for capability in discovered:
        model = existing.get(capability.model_name)
        if not model:
            continue
        current_budget = (
            model.context_window_tokens,
            model.context_compaction_threshold_tokens,
            model.max_output_tokens,
            model.tool_result_max_tokens,
        )
        legacy_discovery_budget = (
            capability.context_window_tokens,
            capability.context_compaction_threshold_tokens,
            capability.max_output_tokens,
            DEFAULT_TOOL_RESULT_MAX_TOKENS,
        )
        # Before durable tool-output storage, discovery derived the cap from
        # the whole input window. Treat only that exact automatic value as
        # legacy; any other number remains an administrator's choice.
        legacy_proportional_preview_budget = (
            capability.context_window_tokens,
            capability.context_compaction_threshold_tokens,
            capability.max_output_tokens,
            max(1, capability.context_compaction_threshold_tokens // 16),
        )
        if current_budget not in {
            default_budget,
            legacy_discovery_budget,
            legacy_proportional_preview_budget,
        }:
            continue
        next_budget = (
            capability.context_window_tokens,
            capability.context_compaction_threshold_tokens,
            capability.max_output_tokens,
            capability.tool_result_max_tokens,
        )
        if next_budget == current_budget:
            continue
        (
            model.context_window_tokens,
            model.context_compaction_threshold_tokens,
            model.max_output_tokens,
            model.tool_result_max_tokens,
        ) = next_budget
        changed += 1
    if changed:
        db.commit()
    return changed


class ModelDiscoveryUnsupported(Exception):
    """预设声明该端点没有模型列表接口，不应发出注定失败的请求。"""


def _model_discovery_config(provider_type: str, preset: dict[str, Any] | None) -> dict[str, Any]:
    if preset and isinstance(preset.get("model_discovery"), dict):
        return preset["model_discovery"]
    if provider_type == "anthropic":
        return {"adapter": "anthropic", "path": "/v1/models", "response_key": "data"}
    return {"adapter": "openai_compatible", "path": "/models", "response_key": "data"}


async def _fetch_connection_models(
    provider_type: str, base_url: str, api_key: str, preset: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    config = _model_discovery_config(provider_type, preset)
    adapter = config["adapter"]
    if adapter == "unsupported":
        raise ModelDiscoveryUnsupported(config.get("reason") or "该端点不支持模型列表查询")
    if adapter == "anthropic":
        # 凭证头随网关而异（官方/DeepSeek 用 x-api-key，阿里云/智谱/Kimi 用 Bearer）。
        auth_style = str((preset or {}).get("auth_style") or AUTH_STYLE_API_KEY)
        credential = (
            {"Authorization": f"Bearer {api_key}"}
            if auth_style == AUTH_STYLE_BEARER
            else {"x-api-key": api_key}
        )
        headers = {
            **credential,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        url = f"{base_url.rstrip('/')}{config['path']}"
        params: dict[str, Any] = {"limit": 100}
    elif adapter == "gemini_native":
        headers = {"x-goog-api-key": api_key}
        url = config["url"]
        params = {"pageSize": 100}
    elif adapter == "volcengine_ark":
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        url = f"{base_url.rstrip('/')}{config['path']}"
        params = {}
    else:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        url = f"{base_url.rstrip('/')}{config.get('path', '/models')}"
        params = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()

    raw_models = payload.get(config.get("response_key", "data")) or payload.get("data") or payload.get("models") or []
    if isinstance(raw_models, dict):
        raw_models = list(raw_models.values())
    if not isinstance(raw_models, list):
        return []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_models:
        if isinstance(item, str):
            model_name = item
        elif isinstance(item, dict):
            if adapter == "gemini_native":
                supported_methods = item.get("supportedGenerationMethods") or []
                if supported_methods and "generateContent" not in supported_methods:
                    continue
                model_name = item.get("name")
                prefix = config.get("strip_prefix", "")
                if isinstance(model_name, str) and prefix and model_name.startswith(prefix):
                    model_name = model_name[len(prefix) :]
            elif adapter == "volcengine_ark":
                # Ark 的 Endpoint ID 才是 Chat Completions 所需的 model 参数。
                model_name = item.get("endpoint_id") or item.get("id")
            else:
                model_name = item.get("id") or item.get("name") or item.get("model")
        else:
            model_name = None
        if isinstance(model_name, str) and model_name.strip() and model_name not in seen:
            seen.add(model_name)
            models.append(
                {
                    "model_name": model_name,
                    # Keep only the model's own object in memory. The client
                    # receives derived public limits, never a provider's raw
                    # response or arbitrary metadata fields.
                    "metadata": item if isinstance(item, dict) else {},
                }
            )
    return models


async def _fetch_provider_models(
    provider: AIProvider, preset: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return await _fetch_connection_models(
        provider.provider_type.value,
        provider.base_url,
        decrypt_secret(provider.api_key_encrypted),
        preset,
    )


@router.get("", response_model=list[ProviderRead])
def list_providers(db: Session = Depends(get_db)) -> list[ProviderRead]:
    providers = db.query(AIProvider).order_by(AIProvider.id).all()
    return [_to_provider_read(p) for p in providers]


@router.get("/presets", response_model=list[ProviderPresetRead])
def list_presets() -> list[ProviderPresetRead]:
    """返回内置预设；目录数据来自 models.dev，密钥不会参与该接口。"""
    return [_to_preset_read(preset) for preset in list_provider_presets()]


@router.post("/presets/{preset_id}/install", response_model=ProviderRead)
def install_preset(
    preset_id: str, payload: PresetInstallRequest, db: Session = Depends(get_db)
) -> ProviderRead:
    preset = get_provider_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型预设不存在")

    models_by_name = {model["model_name"]: model for model in preset["models"]}
    discovered_by_name = {item.model_name: item for item in payload.model_capabilities}
    unexpected_capabilities = set(discovered_by_name) - set(payload.model_names)
    if unexpected_capabilities:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="安装模型能力信息与所选模型不一致")

    install_models: list[dict[str, Any]] = []
    for model_name in payload.model_names:
        preset_model = models_by_name.get(model_name) or find_model_preset(model_name) or {
            "model_name": model_name,
            "display_name": model_name,
            "thinking_config": {},
        }
        capability = discovered_by_name.get(model_name)
        merged = {**preset_model, **(capability.model_dump() if capability else {})}
        _validate_model_budget(
            context_window_tokens=int(merged.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)),
            context_compaction_threshold_tokens=int(
                merged.get("context_compaction_threshold_tokens", DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS)
            ),
            max_output_tokens=int(merged.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
            tool_result_max_tokens=int(merged.get("tool_result_max_tokens", DEFAULT_TOOL_RESULT_MAX_TOKENS)),
        )
        install_models.append(merged)

    if payload.set_as_default:
        db.query(AIModel).update({AIModel.is_default: False})

    provider = AIProvider(
        name=payload.name or preset["name"],
        provider_type=preset["provider_type"],
        base_url=preset["base_url"],
        api_key_encrypted=encrypt_secret(payload.api_key),
    )
    db.add(provider)
    db.flush()
    for index, preset_model in enumerate(install_models):
        # 从供应商 /models 列表获取的新模型不必等待本地目录更新；没有已知能力映射时
        # 仍可安全安装，思考参数会保持自动模式，管理员可在模型编辑里补充高级配置。
        db.add(
            AIModel(
                provider_id=provider.id,
                model_name=preset_model["model_name"],
                display_name=preset_model["display_name"],
                description=preset_model.get("description", ""),
                context_window_tokens=int(preset_model.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)),
                context_compaction_threshold_tokens=int(
                    preset_model.get("context_compaction_threshold_tokens", DEFAULT_CONTEXT_COMPACTION_THRESHOLD_TOKENS)
                ),
                max_output_tokens=int(preset_model.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
                tool_result_max_tokens=int(
                    preset_model.get("tool_result_max_tokens", DEFAULT_TOOL_RESULT_MAX_TOKENS)
                ),
                is_default=payload.set_as_default and index == 0,
                is_multimodal=bool(preset_model.get("is_multimodal", False)),
                supports_disabled_thinking=bool(preset_model.get("supports_disabled_thinking", True)),
                thinking_config=_effective_thinking_config(
                    provider.base_url, preset_model.get("thinking_config")
                ),
            )
        )
    db.commit()
    db.refresh(provider)
    return _to_provider_read(provider)


@router.post("/presets/{preset_id}/discover-models", response_model=ModelDiscoveryResult)
async def discover_preset_models(
    preset_id: str, payload: PresetDiscoveryRequest
) -> ModelDiscoveryResult:
    """使用尚未保存的 API Key 查询预设供应商的当前可用模型。"""
    preset = get_provider_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型预设不存在")
    try:
        models = await _fetch_connection_models(
            str(preset["provider_type"]), preset["base_url"], payload.api_key, preset
        )
    except ModelDiscoveryUnsupported as exc:
        # 预期情况，不是故障：这类套餐端点只有 /v1/messages。直接展示内置模型，
        # 且不要提示「检查 API Key」——此时密钥并未被验证过。
        return ModelDiscoveryResult(
            models=[
                _model_discovery_item({"model_name": model["model_name"], "metadata": {}}, preset, CATALOG_SOURCE)
                for model in preset["models"]
            ],
            source=CATALOG_SOURCE,
            warning=f"{exc}，已列出该套餐的内置模型；如需其他模型可在添加后手动补充。",
        )
    except httpx.HTTPStatusError as exc:
        status_text = f"HTTP {exc.response.status_code}"
        models = []
    except httpx.RequestError as exc:
        status_text = f"网络请求失败：{exc}"
        models = []
    except (TypeError, ValueError) as exc:
        status_text = f"模型列表响应无法解析：{exc}"
        models = []
    else:
        status_text = ""

    if models:
        discovered = [_model_discovery_item(model, preset, "供应商接口") for model in models]
        return ModelDiscoveryResult(
            models=discovered,
            source="供应商接口",
        )
    return ModelDiscoveryResult(
        models=[
            _model_discovery_item({"model_name": model["model_name"], "metadata": {}}, preset, CATALOG_SOURCE)
            for model in preset["models"]
        ],
        source=CATALOG_SOURCE,
        warning=(
            f"未能从供应商接口获取模型（{status_text or '接口未返回模型'}）。"
            + ("已显示内置预设。" if preset["models"] else "该供应商没有过期的内置模型可回退，请检查 API Key 后重试。")
        ),
    )


@router.post("", response_model=ProviderRead)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> ProviderRead:
    provider = AIProvider(
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url.rstrip("/"),
        api_key_encrypted=encrypt_secret(payload.api_key),
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _to_provider_read(provider)


@router.patch("/{provider_id}", response_model=ProviderRead)
def update_provider(provider_id: int, payload: ProviderUpdate, db: Session = Depends(get_db)) -> ProviderRead:
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")

    if payload.name is not None:
        provider.name = payload.name
    if payload.base_url is not None:
        provider.base_url = payload.base_url.rstrip("/")
    if payload.api_key:
        provider.api_key_encrypted = encrypt_secret(payload.api_key)

    db.commit()
    db.refresh(provider)
    return _to_provider_read(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> None:
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")
    db.delete(provider)
    db.commit()


@router.post("/{provider_id}/models", response_model=ModelRead)
def create_model(provider_id: int, payload: ModelCreate, db: Session = Depends(get_db)) -> AIModel:
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")

    if payload.is_default:
        db.query(AIModel).update({AIModel.is_default: False})

    _validate_model_budget(
        context_window_tokens=payload.context_window_tokens,
        context_compaction_threshold_tokens=payload.context_compaction_threshold_tokens,
        max_output_tokens=payload.max_output_tokens,
        tool_result_max_tokens=payload.tool_result_max_tokens,
    )

    model = AIModel(
        provider_id=provider_id,
        model_name=payload.model_name,
        display_name=payload.display_name,
        description=payload.description,
        context_window_tokens=payload.context_window_tokens,
        context_compaction_threshold_tokens=payload.context_compaction_threshold_tokens,
        max_output_tokens=payload.max_output_tokens,
        tool_result_max_tokens=payload.tool_result_max_tokens,
        is_default=payload.is_default,
        is_multimodal=payload.is_multimodal,
        supports_disabled_thinking=payload.supports_disabled_thinking,
        thinking_config=_effective_thinking_config(provider.base_url, payload.thinking_config),
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.patch("/models/{model_id}", response_model=ModelRead)
def update_model(model_id: int, payload: ModelUpdate, db: Session = Depends(get_db)) -> AIModel:
    model = db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")

    if payload.is_default:
        db.query(AIModel).update({AIModel.is_default: False})
    _validate_model_budget(
        context_window_tokens=(payload.context_window_tokens if payload.context_window_tokens is not None else model.context_window_tokens),
        context_compaction_threshold_tokens=(
            payload.context_compaction_threshold_tokens
            if payload.context_compaction_threshold_tokens is not None
            else model.context_compaction_threshold_tokens
        ),
        max_output_tokens=(payload.max_output_tokens if payload.max_output_tokens is not None else model.max_output_tokens),
        tool_result_max_tokens=(
            payload.tool_result_max_tokens
            if payload.tool_result_max_tokens is not None
            else model.tool_result_max_tokens
        ),
    )
    if payload.display_name is not None:
        model.display_name = payload.display_name
    if payload.description is not None:
        model.description = payload.description
    if payload.context_window_tokens is not None:
        model.context_window_tokens = payload.context_window_tokens
    if payload.context_compaction_threshold_tokens is not None:
        model.context_compaction_threshold_tokens = payload.context_compaction_threshold_tokens
    if payload.max_output_tokens is not None:
        model.max_output_tokens = payload.max_output_tokens
    if payload.tool_result_max_tokens is not None:
        model.tool_result_max_tokens = payload.tool_result_max_tokens
    if payload.is_default is not None:
        model.is_default = payload.is_default
    if payload.is_multimodal is not None:
        model.is_multimodal = payload.is_multimodal
    if payload.supports_disabled_thinking is not None:
        model.supports_disabled_thinking = payload.supports_disabled_thinking
    if payload.thinking_config is not None:
        model.thinking_config = _effective_thinking_config(model.provider.base_url, payload.thinking_config)
    if payload.access_mode is not None:
        model.access_mode = payload.access_mode
    allowed_users, allowed_groups = _validate_access_targets(db, payload.allowed_user_ids, payload.allowed_group_ids)
    if allowed_users is not None:
        model.allowed_users = allowed_users
    if allowed_groups is not None:
        model.allowed_groups = allowed_groups

    db.commit()
    db.refresh(model)
    return model


@router.post("/{provider_id}/discover-models", response_model=ModelDiscoveryResult)
async def discover_models(provider_id: int, db: Session = Depends(get_db)) -> ModelDiscoveryResult:
    """通过供应商的模型列表接口拉取可用模型；失败时回退到同供应商预设。"""
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")

    preset = find_provider_preset(provider.base_url, provider.provider_type.value)
    try:
        models = await _fetch_provider_models(provider, preset)
    except ModelDiscoveryUnsupported as exc:
        return ModelDiscoveryResult(
            models=[
                _model_discovery_item({"model_name": model["model_name"], "metadata": {}}, preset, CATALOG_SOURCE)
                for model in (preset["models"] if preset else [])
            ],
            source=CATALOG_SOURCE,
            warning=f"{exc}，已列出该套餐的内置模型；如需其他模型可在添加后手动补充。",
        )
    except httpx.HTTPStatusError as exc:
        status_text = f"HTTP {exc.response.status_code}"
        models = []
    except httpx.RequestError as exc:
        status_text = f"网络请求失败：{exc}"
        models = []
    except (TypeError, ValueError) as exc:
        status_text = f"模型列表响应无法解析：{exc}"
        models = []
    else:
        status_text = ""

    if models:
        discovered = [_model_discovery_item(model, preset, "供应商接口") for model in models]
        synced = _sync_default_discovered_budgets(db, provider.id, discovered)
        return ModelDiscoveryResult(
            models=discovered,
            source="供应商接口",
            warning=(f"已自动更新 {synced} 个仍使用保守默认预算的已添加模型。" if synced else None),
        )

    if preset:
        return ModelDiscoveryResult(
            models=[
                _model_discovery_item({"model_name": model["model_name"], "metadata": {}}, preset, CATALOG_SOURCE)
                for model in preset["models"]
            ],
            source=CATALOG_SOURCE,
            warning=f"未能从供应商接口获取模型（{status_text or '接口未返回模型'}），已显示内置预设。",
        )

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"无法获取模型列表：{status_text or '接口未返回模型'}",
    )


@router.post("/{provider_id}/models/bulk", response_model=ModelBulkCreateResult)
def create_models_bulk(
    provider_id: int, payload: ModelBulkCreateRequest, db: Session = Depends(get_db)
) -> ModelBulkCreateResult:
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")

    existing_names = {
        row[0]
        for row in db.query(AIModel.model_name).filter(AIModel.provider_id == provider_id).all()
    }
    created: list[AIModel] = []
    skipped_model_names: list[str] = []
    for item in payload.models:
        if item.model_name in existing_names:
            skipped_model_names.append(item.model_name)
            continue
        model = AIModel(
            provider_id=provider_id,
            model_name=item.model_name,
            display_name=item.display_name,
            description=item.description,
            context_window_tokens=item.context_window_tokens,
            context_compaction_threshold_tokens=item.context_compaction_threshold_tokens,
            max_output_tokens=item.max_output_tokens,
            tool_result_max_tokens=item.tool_result_max_tokens,
            thinking_config=_effective_thinking_config(provider.base_url, item.thinking_config),
            is_multimodal=item.is_multimodal,
            supports_disabled_thinking=item.supports_disabled_thinking,
            is_default=False,
        )
        db.add(model)
        created.append(model)
        existing_names.add(item.model_name)
    db.commit()
    for model in created:
        db.refresh(model)
    return ModelBulkCreateResult(created=created, skipped_model_names=skipped_model_names)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_model(model_id: int, db: Session = Depends(get_db)) -> None:
    model = db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")
    db.delete(model)
    db.commit()


@router.post("/{provider_id}/test", response_model=TestConnectionResult)
async def test_provider_connection(
    provider_id: int, payload: TestConnectionRequest, db: Session = Depends(get_db)
) -> TestConnectionResult:
    provider = db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider 不存在")

    client = build_ai_client(provider)
    start = time.monotonic()
    try:
        result = await client.chat(
            model=payload.model_name,
            messages=[{"role": "user", "content": "This is a connectivity test. Reply with exactly one word: pong"}],
            max_tokens=8,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return TestConnectionResult(
            success=True,
            message=f"连接成功（{latency_ms} ms），模型返回：{result.content.strip()[:80] or '(空)'}",
            latency_ms=latency_ms,
        )
    except httpx.HTTPStatusError as e:
        return TestConnectionResult(
            success=False, message=f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        )
    except httpx.RequestError as e:
        return TestConnectionResult(success=False, message=f"网络请求失败: {e}")
    except Exception as e:  # noqa: BLE001 兜底捕获，避免第三方 SDK/接口的未知异常导致 500
        return TestConnectionResult(success=False, message=f"未知错误: {e}")
