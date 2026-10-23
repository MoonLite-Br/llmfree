# Changelog

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
