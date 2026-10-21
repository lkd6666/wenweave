"""Repair transport shapes without inventing tool arguments or document facts."""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError


def decode_tool_arguments(value: Any) -> dict[str, Any]:
    """Require complete JSON, including gateways that encode the object twice."""
    for _ in range(2):
        if not isinstance(value, str):
            break
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("工具参数必须是 JSON 对象")
    return value


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref", "")
    if reference.startswith("#/$defs/"):
        return root.get("$defs", {}).get(reference.removeprefix("#/$defs/"), schema)
    return schema


def _accepts_null(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "null" or any(
        _accepts_null(branch) for branch in schema.get("anyOf", [])
    )


def _normalise_value(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> Any:
    schema = _resolve(schema, root)
    branches = schema.get("anyOf", [])
    if branches:
        # Never decode a string if the actual schema accepts strings (e.g. a
        # read cursor). In particular HTML, tokens and IDs stay byte-for-byte.
        if isinstance(value, str) and any(branch.get("type") == "string" for branch in branches):
            return value
        for branch in branches:
            resolved = _resolve(branch, root)
            if resolved.get("type") in {"array", "object"}:
                return _normalise_value(value, resolved, root)
        return value
    expected = schema.get("type")
    if isinstance(value, str) and expected in {"array", "object"}:
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return value
        if (expected == "array" and isinstance(decoded, list)) or (
            expected == "object" and isinstance(decoded, dict)
        ):
            value = decoded
    if expected == "array" and isinstance(value, list):
        return [_normalise_value(item, schema.get("items", {}), root) for item in value]
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        return {
            key: _normalise_value(item, properties.get(key, {}), root)
            for key, item in value.items()
            if not (
                item is None
                and key in properties
                and key not in required
                and not _accepts_null(properties[key])
            )
        }
    return value


def normalise_tool_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Handle unambiguous wrappers, aliases, JSON containers and optional nulls."""
    arguments = dict(arguments)
    properties = schema.get("properties", {})
    for _ in range(2):
        if len(arguments) != 1 or any(key in properties for key in arguments):
            break
        wrapper = next(iter(arguments))
        if wrapper not in {"arguments", "args", "parameters", "input"}:
            break
        try:
            arguments = decode_tool_arguments(arguments[wrapper])
        except (ValueError, TypeError, RecursionError):
            break
    if "query" in properties and "query" not in arguments:
        aliases = [key for key in ("keyword", "keywords", "search_query", "search_term") if key in arguments]
        if len(aliases) == 1 and isinstance(arguments[aliases[0]], str):
            arguments["query"] = arguments.pop(aliases[0])
    if "block_ids" in properties and "block_ids" not in arguments and "block_id" in arguments:
        arguments["block_ids"] = arguments.pop("block_id")
    for key in ("block_ids", "template_ids", "component_ids"):
        if key not in properties or key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                decoded = value
            if isinstance(decoded, list):
                arguments[key] = decoded
            elif value.strip() and not value.lstrip().startswith(("[", "{")):
                arguments[key] = [value]
        elif key == "template_ids" and isinstance(value, int) and not isinstance(value, bool):
            arguments[key] = [value]
    return _normalise_value(arguments, schema, schema)


def tool_argument_error(
    name: str,
    schema: dict[str, Any],
    *,
    validation: ValidationError | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Give the model precise, compact corrections without echoing raw inputs."""
    field_errors = []
    missing_fields = []
    if validation is not None:
        for error in validation.errors(include_url=False, include_context=False, include_input=False)[:12]:
            path = ".".join(str(part) for part in error["loc"])
            missing = error["type"] == "missing"
            if missing:
                missing_fields.append(path)
            field_errors.append({
                "field": path,
                "code": error["type"],
                "message": "必填参数未提供" if missing else error["msg"],
            })
    if not reason:
        reason = (
            f"{name} 缺少必填参数：{'、'.join(missing_fields)}"
            if missing_fields else f"{name} 的工具参数格式不正确"
        )
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    expected = {
        key: {field: value for field, value in properties.get(key, {}).items() if field in {"type", "description", "enum", "anyOf"}}
        for key in dict.fromkeys([*required, *(error["field"].split(".")[0] for error in field_errors)])
    }
    next_step = (
        "请根据 required_fields 和 field_errors 修正参数，再调用同一工具；不要原样重复失败调用。"
        "示例只展示参数格式，ID、revision 和 hash 必须从实际工具结果原样复制。"
    )
    example = None
    if "query" in required:
        next_step += "query 必须填写用户目标中的真实正文关键词；无法确定目标时先定位或向用户确认，不要传空对象。"
        example = {"query": "目标正文关键词"}
    if "block_ids" in required:
        next_step += "block_ids 必须来自对应搜索结果；没有目标 ID 时先搜索定位。"
        example = {"block_ids": ["从搜索结果复制的 block_id"]}
    if "version_id" in required:
        next_step += "version_id 必须来自 list_history_versions 的实际结果。"
    if "revision" in required:
        next_step += "必须保留实际 revision；不能补造版本号或在缺参时执行写入。"
    return {
        "ok": False,
        "code": "invalid_tool_arguments",
        "tool": name,
        "error": reason,
        "recoverable": True,
        "required_fields": required,
        "missing_fields": missing_fields,
        "field_errors": field_errors,
        "expected_arguments": expected,
        **({"example_arguments": example} if example and set(required).issubset(example) else {}),
        "next_step": next_step,
    }


def prepare_tool_arguments(
    name: str, arguments: Any, tool_instance: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    args_schema = getattr(tool_instance, "args_schema", None)
    schema = args_schema.model_json_schema() if hasattr(args_schema, "model_json_schema") else {}
    try:
        decoded = decode_tool_arguments(arguments)
    except (ValueError, TypeError, RecursionError):
        return {}, tool_argument_error(name, schema, reason=f"{name} 的参数不是完整的 JSON 对象，请重新生成完整参数")
    normalised = normalise_tool_arguments(decoded, schema)
    # ask_user has its own permissive option parser and bounded text fallback.
    # Keep those semantics instead of rejecting its provider-specific wrappers.
    if name != "ask_user" and hasattr(args_schema, "model_validate"):
        try:
            args_schema.model_validate(normalised)
        except ValidationError as exc:
            return normalised, tool_argument_error(name, schema, validation=exc)
    if "query" in schema.get("required", []) and isinstance(normalised.get("query"), str) and not normalised["query"].strip():
        return normalised, tool_argument_error(name, schema, reason=f"{name} 的 query 不能为空，请填写真实搜索关键词")
    return normalised, None
