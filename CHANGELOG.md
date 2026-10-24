# Changelog

## 0.3.0
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
