# Changelog

## 0.6.2
- Release packaging: full English README, correct GitHub/PyPI URLs, static version badges.
- Ships the load-aware routing + serve concurrency work documented under 0.6.1.

## 0.6.1
- **Load-aware routing** (threads, `race`, `llmf serve`): each provider has a cap of simultaneous requests
  (`Client(max_inflight=6)`, per-provider `ProviderSpec.concurrency`: ch-at 8, llm7 3, pollinations 1). Extra calls no
  longer queue behind a busy or rate-slotted provider; they spill to the next one, re-ranked live. On a local benchmark
  (30 threads, slow first provider) mean latency went 1.40 s -> 0.62 s and p50 1.25 s -> 0.18 s.
- `llmf serve`: `--max-concurrent N` (default 48) answers `429 {"code": "busy"}` + `Retry-After: 1` instead of letting
  clients time out in a queue; listen backlog raised from the stdlib's 5 to 128 (bursts stalled 7-11 s in the connect phase).
- `llmf serve --host 8000` (port in the host slot) now prints a one-line hint instead of a traceback; same for "port in use".

## 0.6.0
- **Vetted catalogue**: a model stays only if it answered in >= 2 independent real-network runs with >= 75 % success.
  Removed: rewind-ai llama-3.1-8b / qwen-2.5-72b (sign-in only), kilo-openrouter nemotron-3-super-120b, minimax-m3.1-flash,
  laguna-xs-2.1, nemotron-3-nano-omni (capacity), ovh Meta-Llama-3.3-70B and Qwen3.5-9B (slow / 429), llm7 minimax-m2.7
  (503/429 half the time), blockrun laguna-xs-2.1 / muse-glimmer / north-mini-code, unverified chatai models.
  Ids that are not catalogued still work (`provider/model`) and show up with `llmf models --live`.
- **Survival history**: every `doctor` run is appended to `history.json` (last 20 results per model).
  `llmf models` shows `alive 7/7` / `flaky 2/3` / `dead 0/3`; a model with >= 3 samples and < 50 % success sinks to the
  end of every plan automatically. `ModelInfo.alive` / `.samples` expose the same.
- Tags: `fast` = codestral, chatjimmy, gpt-oss:20b, pollinations, Mistral-Nemo, kilo-auto/small; `reasoning` ends with BlockRun nano-omni.
- **Optional browser-like transport**: `LLMF(transport="auto" | "curl_cffi", impersonate="chrome")`,
  `--transport`, `--impersonate`, `LLMF_TRANSPORT`, `LLMF_IMPERSONATE`. Uses `curl_cffi` (TLS/HTTP2 fingerprint of a
  real Chrome) when installed: `pip install "llmf[stealth]"`. Still **zero required dependencies**; the stdlib
  transport stays the default and is what `auto` falls back to when the package is missing or misbehaves.
- `llmf -v version` prints the active transport; `live_test.py` has a `transport` group (skipped if not installed).
- `vision` tag order: ovh Qwen2.5-VL -> kilo super-vl -> freeai qwen7b -> blockrun (last; often 429 capacity).
- `ModelSpec.streams` / `ModelInfo.streaming`: `chatjimmy` is known to answer in one piece; `llmf models` shows `no-stream`.
- `llmf models` has a dedicated `ALIVE` column (`alive 7/7`, `flaky 2/3`, `dead 0/3`, or `-` before the first doctor run).
- "Retry after N seconds" now cools the provider down for N+1 s (was 3N+2).
- `live_test.py`: provider checks that fail only with HTTP 429 are WARN (not FAIL); known non-streaming models pass.

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
