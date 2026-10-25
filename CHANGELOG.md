# Changelog

## 0.5.1
- Documentation: full PyPI/README (API, CLI, pip show, 0.5.0 providers). No code changes vs 0.5.0.

## 0.5.0
- New providers: `ch-at` (GPT-4o, no auth, no /models; first in the chain and in the `best` tag), `rewind-ai`
  (`qwen/qwen-2.5-7b-instruct`, `gpt-4o-mini`; trailing-slash path + `Origin` header; sign-in-only models are marked broken),
  and `nottrack` (SSE "debate" endpoint, new `nottrack` adapter; **opt-in only**: never in the automatic chain).
- `ProviderSpec.auto=False` keeps a provider out of the automatic chain (still usable with `provider=`).
- BlockRun: default model is now `nemotron-3.5-lightning`; added `laguna-xs-2.1`, `muse-glimmer-30b`.
- Pollinations: `openai-fast` is an alias of `openai` (they are the same model).

## 0.4.1
- Fix: "capacity exhausted ... or use a paid model" (BlockRun) was read as *paid* and put the model to sleep for
  hours; capacity now wins (10 min). `cohere/north-mini-code` on BlockRun is no longer marked broken.
- 429 with "Retry after N seconds" now cools down ~3xN seconds instead of a flat 60 s; llm7 gets `min_interval=1.1`.
- ovh default model is now `gpt-oss-120b` (~2 s) instead of Llama-3.3-70B (7-30 s / 429 on anonymous tier).
- Live-id filter also drops freeai utility models (madlad, realesrgan, rmbg, demucs, deoldify, step1x-edit, sam).

## 0.4.0
- Errors: 429 is now split into plain rate-limit (provider sleeps 60 s), capacity / `ResourceExhausted`
  (only that model sleeps 10 min) and "use a paid model" (model sleeps hours).
- `models.check()` / `llmf doctor --all` / `models.list(live=True)` are chat-only and free-only by default:
  guard/safety, whisper/tts/embedding/image/video/OCR and priced models are skipped
  (`include_non_chat=True` / `--include-non-chat` to override).
- New `vision_timeout` (default 90 s) used for requests with images and for vision models in `doctor`.
- `fast` tag is dynamic: models measured <= 1 s join it, ordered by latency; failing ones sink. Static order
  refreshed from measurements (llm7 minimax-m2.7 / codestral, chatjimmy, ...); `best` leads with nemotron-3-ultra.
- Catalogue: llm7 gets `gpt-oss:20b`, `minimax-m2.7`, `codestral-latest`; blockrun `cohere/north-mini-code` marked broken.

## 0.3.0
- `freeai` rewritten from live evidence: models `qwen7b` / `qwen-coder` / `deepseek-r1`, moved up the chain;
  `/v1/models` is read from the `models` key and paid (non-self-hosted) models are ignored;
  `premium_requires_purchase` errors put the model to sleep for hours.
- Explicit `proxy=` is no longer bypassed by the `no_proxy` environment variable; proxy credentials in the URL are sent.
- Added `live_test.py`: end-to-end check of everything against the real internet, with a JSON report.
- **API**: OpenAI-shaped `LLMF().chat.completions.create(...)` returning `ChatCompletion` / `ChatStream`
  (`choices[0].message.content`, `usage`, `output_text`); `llm.models.list/check/resolve`,
  `llm.providers.list`, `llm.health.check`. The old shorthand (`llmf.chat("hi")`) still works.
- **SOCKS**: socks4 / socks4a / socks5 / socks5h proxies, pure stdlib.
- **`llmf doctor`** / `models.check()`: really calls every model, optionally including live ids (`--all`);
  results are cached for 24 h and used to demote failing targets and rank by latency.
- **Routing**: `routing="adaptive"` (latency EWMA) and `race=N` (parallel hedged requests).
- Catalogue: marked `minimax-m3.1-flash:free` and `nemotron-3-super-120b-a12b:free` (Kilo) as broken;
  `fast` tag re-ordered from measured latencies.
- CLI: `ask`, `chat`, `models [list|check|resolve]`, `doctor`, table output, `--routing`, `--race`.
- `import llmf` no longer loads asyncio / thread pools / SOCKS / server up front.

## 0.2.0
- New provider `chatai` (CSRF/session flow, SSE, respects the daily limit with a long cooldown).
- New `llmf.tools.ask_langchain_docs()` (guest-token docs agent; not part of the chat chain).
- New `proxy=` option on `Client`/`configure`, `--proxy` CLI flag and `LLMF_PROXY` env (user-supplied http/https proxy).
- New `llmf serve`: local OpenAI-compatible server (chat completions + SSE streaming, models, health; localhost/no-CORS by default, optional bearer key).
- `-p/--provider` flag and `provider=` argument; per-call `proxy=`.
- README: provider speed table.

## 0.1.0
- First release: unified `chat` / `stream` / `session` / async API, 8 built-in keyless providers,
  automatic fallback with cooldown and rate-limit awareness, CLI, optional stillworks discovery.
