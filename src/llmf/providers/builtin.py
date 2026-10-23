"""The built-in catalogue of free, keyless endpoints (verified 2026-10-22).

Order of ``BUILTIN`` is the global fallback chain: fastest/cleanest first.
Endpoints can disappear at any time – that is exactly why llmf falls back.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .base import ModelSpec as M
from .base import ProviderSpec

_KILO_HEADERS = {"Authorization": "Bearer anonymous", "X-KILOCODE-EDITORNAME": "kilo"}

BUILTIN: List[ProviderSpec] = [
    ProviderSpec(
        name="ovh",
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("ovhcloud",),
        default_model="Meta-Llama-3_3-70B-Instruct",
        models=[
            M("Meta-Llama-3_3-70B-Instruct", aliases=("llama3.3", "llama-3.3-70b")),
            M("Qwen3.5-397B-A17B"),
            M("Qwen3.5-9B"),
            M("gpt-oss-120b"),
            M("Mistral-Nemo-Instruct-2407"),
            M("Qwen2.5-VL-72B-Instruct", vision=True),
        ],
        note="Fast and clean. Anonymous tier of OVHcloud AI Endpoints.",
    ),
    ProviderSpec(
        name="kilo-openrouter",
        base_url="https://api.kilo.ai",
        chat_path="/api/openrouter/chat/completions",
        models_path="/api/gateway/models",
        headers=_KILO_HEADERS,
        aliases=("kilo",),
        free_suffix=":free",
        default_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        models=[
            M("nvidia/nemotron-3-ultra-550b-a55b:free"),
            M("nvidia/nemotron-3-super-120b-a12b:free"),
            M("minimax/minimax-m3.1-flash:free"),
            M("nvidia/nemotron-3.5-lightning:free"),
            M("cohere/north-mini-code:free"),
            M("nvidia/nemotron-3.5-super-vl:free", vision=True, verified=False),
            M("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"),
            M("dots-studio/dots-3-note-preview:free"),
            M("liquid/lfm-2.5-2.6b:free"),
            M("poolside/laguna-s-2.1:free", verified=False),
            M("poolside/laguna-xs-2.1:free", verified=False),
        ],
        note="Strongest free model. ~200 requests/hour/IP.",
    ),
    ProviderSpec(
        name="chatjimmy",
        base_url="https://chatjimmy.ai",
        chat_path="/api/chat",
        models_path="/api/models",
        kind="chatjimmy",
        aliases=("jimmy",),
        default_model="llama3.1-8B",
        models=[M("llama3.1-8B", aliases=("llama3.1", "llama-3.1-8b"))],
        note="Extremely fast Llama 3.1 8B; custom response format.",
    ),
    ProviderSpec(
        name="kilo-gateway",
        base_url="https://api.kilo.ai",
        chat_path="/api/gateway/chat/completions",
        models_path="/api/gateway/models",
        aliases=("kilo",),
        free_suffix=":free",
        default_model="kilo-auto/free",
        models=[
            M("kilo-auto/free"),
            M("kilo-auto/small"),
            M("openrouter/free"),
            M("minimax/minimax-m3.1-flash:free"),
            M("dots-studio/dots-3-note-preview:free"),
        ],
        note="Auto-routing gateway; no headers needed.",
    ),
    ProviderSpec(
        name="pollinations",
        base_url="https://text.pollinations.ai",
        chat_path="/openai",
        models_path="/models",
        aliases=("poll",),
        min_interval=15.0,
        default_model="openai",
        models=[M("openai", aliases=("gpt-oss", "gpt-oss-20b"))],
        note="Anonymous tier: 1 request / 15 s.",
    ),
    ProviderSpec(
        name="llm7",
        base_url="https://api.llm7.io",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("llm7.io",),
        default_model="gpt-oss:20b",
        models=[M("gpt-oss:20b", aliases=("gpt-oss",))],
        note="Stable, small model.",
    ),
    ProviderSpec(
        name="blockrun",
        base_url="https://blockrun.ai",
        chat_path="/api/v1/chat/completions",
        models_path="/api/v1/models",
        default_model="nvidia/nemotron-3-ultra-550b",
        models=[
            M("nvidia/nemotron-3-ultra-550b"),
            M("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"),
            M("nvidia/llama-3.2-11b-vision", vision=True),
            M("nvidia/nemotron-3.5-lightning"),
            M("cohere/north-mini-code"),
        ],
        note="Upstream times out after ~12 s, so it can be flaky.",
    ),
    ProviderSpec(
        name="freeai",
        base_url="https://api.free.ai",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("free.ai",),
        default_model="deepseek-r1-7b",
        models=[
            M("deepseek-r1-7b", aliases=("deepseek-r1", "r1")),
            M("qwen-vl", vision=True),
        ],
        note="Only verified indirectly (via stillworks).",
    ),
    ProviderSpec(
        name="chatai",
        base_url="https://chatai.org",
        chat_path="/api/chat",
        kind="chatai",
        default_model="openai/gpt-5.6-luna",
        models=[
            M("openai/gpt-5.6-luna"),
            M("anthropic/claude-haiku-5.5"),
            M("google/gemini-2.5-flash-lite"),
            M("x-ai/grok-4", verified=False),
            M("anthropic/claude-opus-5", verified=False),
            M("google/gemini-3.1-pro", verified=False),
        ],
        note="Premium models but only ~3-5 requests/IP/day; last-resort in the chain.",
    ),
]

# Intent aliases -> ordered (provider, model) targets.
TAGS: Dict[str, List[Tuple[str, str]]] = {
    "fast": [
        ("chatjimmy", "llama3.1-8B"),
        ("kilo-gateway", "kilo-auto/small"),
        ("ovh", "Qwen3.5-9B"),
        ("kilo-openrouter", "minimax/minimax-m3.1-flash:free"),
        ("llm7", "gpt-oss:20b"),
    ],
    "best": [
        ("kilo-openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        ("ovh", "Qwen3.5-397B-A17B"),
        ("blockrun", "nvidia/nemotron-3-ultra-550b"),
        ("ovh", "gpt-oss-120b"),
        ("ovh", "Meta-Llama-3_3-70B-Instruct"),
    ],
    "code": [
        ("kilo-openrouter", "cohere/north-mini-code:free"),
        ("blockrun", "cohere/north-mini-code"),
        ("ovh", "Qwen3.5-397B-A17B"),
        ("kilo-openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ],
    "vision": [
        ("ovh", "Qwen2.5-VL-72B-Instruct"),
        ("freeai", "qwen-vl"),
        ("blockrun", "nvidia/llama-3.2-11b-vision"),
        ("kilo-openrouter", "nvidia/nemotron-3.5-super-vl:free"),
    ],
    "reasoning": [
        ("ovh", "gpt-oss-120b"),
        ("kilo-openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"),
        ("freeai", "deepseek-r1-7b"),
        ("llm7", "gpt-oss:20b"),
    ],
}
