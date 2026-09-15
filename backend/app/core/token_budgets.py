"""Shared token-budget defaults for model-visible tool results."""

# Match the default maximum output returned by Codex local tools. Full tool
# results are still retained separately and can be read through continuations.
DEFAULT_TOOL_RESULT_MAX_TOKENS = 10_000
