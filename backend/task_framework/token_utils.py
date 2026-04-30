"""
Token counting and model capacity limits for AI Weekly.

Provides:
- count_tokens(text, model) — token counting via tiktoken
- get_model_limits(model) — model → (max_context, max_output) lookup
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model token capacity registry
# ---------------------------------------------------------------------------
MODEL_TOKEN_LIMITS: Dict[str, Tuple[int, int]] = {
    # OpenAI
    "gpt-4o": (128_000, 16_384),
    "gpt-4o-mini": (128_000, 16_384),
    "gpt-4o-mini-2024-07-18": (128_000, 16_384),
    "gpt-4.1": (1_000_000, 32_768),
    "gpt-4.1-2025-04-14": (1_000_000, 32_768),
    "gpt-4.1-mini": (1_000_000, 32_768),
    "gpt-4.5-preview-2025-02-27": (128_000, 16_384),
    "gpt-5-2025-08-07": (1_000_000, 32_768),
    "o3-mini": (128_000, 16_384),
    "o3-mini-2025-01-31": (128_000, 16_384),
    # Anthropic
    "claude-sonnet-4-20250514": (200_000, 8_192),
    "claude-3.5-sonnet-20241022": (200_000, 8_192),
    # Google Gemini
    "gemini-2.5-pro": (1_000_000, 8_192),
    "gemini-2.5-flash": (1_000_000, 8_192),
    "gemini-2.0-flash": (1_000_000, 8_192),
}

DEFAULT_CONTEXT_LIMIT = 128_000
DEFAULT_OUTPUT_LIMIT = 16_384


def get_model_limits(model: str) -> Tuple[int, int]:
    """Return (max_context_tokens, max_output_tokens) for the given model."""
    if model in MODEL_TOKEN_LIMITS:
        return MODEL_TOKEN_LIMITS[model]
    for prefix, limits in sorted(MODEL_TOKEN_LIMITS.items(), key=lambda x: -len(x[0])):
        if model.startswith(prefix):
            return limits
    logger.warning("Unknown model '%s' — using default limits", model)
    return (DEFAULT_CONTEXT_LIMIT, DEFAULT_OUTPUT_LIMIT)


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens using tiktoken, with char-based fallback."""
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4
