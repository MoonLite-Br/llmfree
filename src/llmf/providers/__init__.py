"""Provider specs and adapters."""

from __future__ import annotations

from typing import Dict

from .base import Adapter, Completion, ModelSpec, Options, ProviderSpec
from .chatai import ChatAIAdapter
from .chatjimmy import ChatJimmyAdapter
from .nottrack import NotTrackAdapter
from .openai_compat import OpenAIAdapter

ADAPTERS: Dict[str, Adapter] = {
    "openai": OpenAIAdapter(),
    "chatjimmy": ChatJimmyAdapter(),
    "chatai": ChatAIAdapter(),
    "nottrack": NotTrackAdapter(),
}

__all__ = ["ADAPTERS", "Adapter", "Completion", "ModelSpec", "Options", "ProviderSpec"]
