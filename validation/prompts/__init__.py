"""Validation prompts module."""
from .ubx_knowledge import (
    build_message_validation_prompt,
    build_config_key_validation_prompt,
    UBX_PROTOCOL_OVERVIEW,
    EXTRACTION_GOTCHAS,
    VERSION_PATTERNS,
    CONFIG_KEY_KNOWLEDGE,
)

__all__ = [
    "build_message_validation_prompt",
    "build_config_key_validation_prompt",
    "UBX_PROTOCOL_OVERVIEW",
    "EXTRACTION_GOTCHAS",
    "VERSION_PATTERNS",
    "CONFIG_KEY_KNOWLEDGE",
]
