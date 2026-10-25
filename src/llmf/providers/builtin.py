"""The built-in catalogue of free, keyless endpoints.

Policy: a model is listed only if it answered in at least 2 independent real-network runs
(2026-10-24/25) with a success rate >= 75%; sign-in-only, 404, or flaky (429/503 half the time)
models are left out. Unknown ids still work (``provider/model`` passes through) and
``llmf doctor --all`` shows what else is live.

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
        name="ch-at",
        base_url="https://ch.at",
        chat_path="/v1/chat/completions",
        aliases=("ch.at",),
        default_model="gpt-4o",
        min_interval=0.6,                      # documented 100 req/min, burst 10
        concurrency=8,
        models=[M("gpt-4o", aliases=("gpt4o", "4o"))],
        note="GPT-4o, no auth, no /models endpoint (only gpt-4o). Documented 100 req/min.",
    ),
    ProviderSpec(
        name="rewind-ai",
        base_url="https://api.rewind.ai",
        chat_path="/v1/chat/completions/",     # the trailing slash is required
        headers={"Origin": "https://rewind.ai"},
        aliases=("rewind",),
        default_model="qwen/qwen-2.5-7b-instruct",
        models=[
            M("qwen/qwen-2.5-7b-instruct", aliases=("qwen-2.5-7b",)),
            M("gpt-4o-mini", aliases=("4o-mini",)),
        ],
        note="Anonymous JWT is issued by the server (30 days); 50/50 requests in 15 s passed.",
    ),
    ProviderSpec(
        name="ovh",
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("ovhcloud",),
        default_model="gpt-oss-120b",
        models=[
            M("gpt-oss-120b"),
            M("Mistral-Nemo-Instruct-2407"),
            M("Qwen3.5-397B-A17B"),
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
            M("nvidia/nemotron-3.5-lightning:free"),
            M("cohere/north-mini-code:free"),
            M("nvidia/nemotron-3.5-super-vl:free", vision=True),
            M("dots-studio/dots-3-note-preview:free"),
            M("liquid/lfm-2.5-2.6b:free"),
            M("poolside/laguna-s-2.1:free"),
        ],
        note="Strongest free model. ~200 requests/hour/IP.",
    ),
    ProviderSpec(
        name="freeai",
        base_url="https://api.free.ai",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("free.ai",),
        default_model="qwen7b",
        models=[
            M("qwen7b", vision=True, aliases=("qwen3.6", "qwen3.6-35b"),
              note="actually Qwen 3.6 35B; handles vision (image input not yet verified)"),
            M("qwen-coder", note="same base as qwen7b, code tuned (chat not yet verified)"),
            M("deepseek-r1", aliases=("r1",), note="reasoning; needs max_tokens >= 200"),
        ],
        note="Self-hosted free models (vLLM). The 500+ OpenRouter models on this site are paid.",
    ),
    ProviderSpec(
        name="chatjimmy",
        base_url="https://chatjimmy.ai",
        chat_path="/api/chat",
        models_path="/api/models",
        kind="chatjimmy",
        aliases=("jimmy",),
        default_model="llama3.1-8B",
        models=[M("llama3.1-8B", aliases=("llama3.1", "llama-3.1-8b"), streams=False,
                  note="replies in one piece (no real streaming); extremely fast anyway")],
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
        concurrency=1,
        default_model="openai",
        models=[M("openai", aliases=("openai-fast", "gpt-oss", "gpt-oss-20b"))],
        note="Anonymous tier: 1 request / 15 s.",
    ),
    ProviderSpec(
        name="llm7",
        base_url="https://api.llm7.io",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        aliases=("llm7.io",),
        default_model="gpt-oss:20b",
        min_interval=1.1,                      # 429 "Retry after 1 seconds" on back-to-back calls
        concurrency=3,
        models=[
            M("gpt-oss:20b", aliases=("gpt-oss",)),
            M("codestral-latest", note="code model, fast"),
        ],
        note="Stable and quick. Some larger/other models answer 429 (capacity).",
    ),
    ProviderSpec(
        name="blockrun",
        base_url="https://blockrun.ai",
        chat_path="/api/v1/chat/completions",
        models_path="/api/v1/models",
        default_model="nvidia/nemotron-3.5-lightning",
        models=[
            M("nvidia/nemotron-3.5-lightning"),
            M("nvidia/nemotron-3-ultra-550b", note="best quality but often 429 capacity / 10-50 s"),
            M("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"),
            M("nvidia/llama-3.2-11b-vision", vision=True),
        ],
        note="Upstream times out after ~12 s, so it can be flaky.",
    ),
    ProviderSpec(
        name="nottrack",
        base_url="https://nottrack.com",
        chat_path="/api/dispatch",
        kind="nottrack",
        headers={"Origin": "https://nottrack.com"},
        aliases=("nottrack-com", "nottrack.com"),
        default_model="debate",
        models=[M("debate", note="multi-speaker, uncensored role-play; long replies")],
        auto=False,
        checkable=False,
        note="Opt-in only (provider=\"nottrack\"): several speakers answer in a debate; use timeout >= 60 s.",
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
        ],
        checkable=False,
        note="Premium models but only ~3-5 requests/IP/day; last-resort in the chain.",
    ),
]

# Intent aliases -> ordered (provider, model) targets.
TAGS: Dict[str, List[Tuple[str, str]]] = {
    # ordered by latencies measured on real networks (2026-10-24); "fast" is re-sorted live by llmf
    "fast": [
        ("llm7", "codestral-latest"),
        ("chatjimmy", "llama3.1-8B"),
        ("llm7", "gpt-oss:20b"),
        ("pollinations", "openai"),
        ("ovh", "Mistral-Nemo-Instruct-2407"),
        ("kilo-gateway", "kilo-auto/small"),
    ],
    "best": [
        ("ch-at", "gpt-4o"),
        ("kilo-openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        ("blockrun", "nvidia/nemotron-3-ultra-550b"),
        ("ovh", "gpt-oss-120b"),
        ("ovh", "Qwen3.5-397B-A17B"),
    ],
    "code": [
        ("kilo-openrouter", "cohere/north-mini-code:free"),
        ("llm7", "codestral-latest"),
        ("ch-at", "gpt-4o"),
        ("freeai", "qwen-coder"),
        ("ovh", "Qwen3.5-397B-A17B"),
        ("kilo-openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ],
    "vision": [
        ("ovh", "Qwen2.5-VL-72B-Instruct"),
        ("kilo-openrouter", "nvidia/nemotron-3.5-super-vl:free"),
        ("freeai", "qwen7b"),
        ("blockrun", "nvidia/llama-3.2-11b-vision"),     # last: often 429 capacity
    ],
    "reasoning": [
        ("ovh", "gpt-oss-120b"),
        ("freeai", "deepseek-r1"),
        ("llm7", "gpt-oss:20b"),
        ("blockrun", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"),
    ],
}
