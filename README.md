<div align="center">

# llmf (llmfree)

**Free, keyless LLMs behind one call: with fallback, a vetted catalogue and an OpenAI-compatible server.**

[![PyPI](https://img.shields.io/pypi/v/llmf?color=2ea44f)](https://pypi.org/project/llmf/)
[![Python](https://img.shields.io/pypi/pyversions/llmf)](https://pypi.org/project/llmf/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/llmf?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/llmf)
[![CI](https://github.com/MoonLite-Br/llmfree/actions/workflows/ci.yml/badge.svg)](https://github.com/MoonLite-Br/llmfree/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Dependencies: 0](https://img.shields.io/badge/dependencies-0-brightgreen)

English · [Tiếng Việt](README.vi.md)

</div>

```bash
pip install -U llmf
```

```python
import llmf
print(llmf.chat("What is the capital of Vietnam?"))   # picks a live free endpoint, falls back on failure
```

No account, no API key, no provider setup. **Standard library only** (zero required dependencies), Python 3.8+,
runs on Linux, macOS, Windows and **Termux/Android**.

> **Heads-up.** These are public, unofficial, free endpoints. They change, throttle or disappear without notice, and your
> prompts go to anonymous third parties. Do not send secrets. Run `llmf doctor` regularly. llmf is not affiliated with any provider.

## Contents

[Features](#features) · [Quick start](#quick-start) · [Python API](#python-api) · [Configuration](#configuration) ·
[CLI](#command-line) · [`llmf doctor`](#llmf-doctor-trust-but-verify) · [`llmf serve`](#llmf-serve-openai-compatible-server) ·
[Going public](#going-public) · [Security](#security-model) · [Providers](#providers) · [Error handling](#error-handling) ·
[Development](#development) · [License](#license)

## Features

| | |
|---|---|
| **One call** | `llmf.chat("...")`, or an OpenAI-shaped `LLM.chat.completions.create(...)`: `choices`, `usage`, `stream=True`, `tools`, `response_format`. |
| **Automatic fallback** | Cooldowns per model / provider, retries, empty-answer and hidden-error detection, `AllProvidersFailed` with a per-attempt report. |
| **Vetted catalogue** | A model is listed only if it answered in ≥ 2 independent real-network runs with ≥ 75 % success. Everything else still works as `provider/model`. |
| **Survival history** | Every `doctor` run is recorded; `llmf models` shows `alive 7/7`, `flaky 2/3`, `dead 0/3` and unreliable models sink automatically. |
| **Load-aware routing** | Per-provider concurrency caps; surplus calls spill to the next provider instead of queueing. `race=N` for the fastest of N. |
| **Aliases** | `fast`, `best`, `code`, `vision`, `reasoning`: ordered, re-ranked live from measured latency. |
| **Proxy + SOCKS** | `http`, `https`, `socks4/4a/5/5h` (pure stdlib). Your own proxy only; llmf never scrapes or rotates public proxies. |
| **Optional browser-like TLS** | `pip install "llmf[stealth]"` adds `curl_cffi` (prebuilt wheels). Falls back to stdlib if unavailable. |
| **`llmf serve`** | OpenAI-compatible HTTP server for any app, extension or addon; can be hardened and exposed to the internet. |
| **Web chat in one flag** | `--ui` built-in chat page, `--html page.html` to host your page, `--app "node main.js"` to run and proxy your own project. |
| **Cloudflare tunnel** | `--cloudflare` publishes the server through your own `cloudflared`, with the hardening profile switched on. |
| **Anti-bot** | Proof-of-work (default) or Cloudflare Turnstile before a browser visitor gets a short-lived, IP-bound session. |

## Quick start

```python
from llmf import LLMF

llm = LLMF()
r = llm.chat.completions.create(
    model="best",
    messages=[{"role": "system", "content": "Be brief."},
              {"role": "user", "content": "What is the capital of Vietnam?"}],
    temperature=0.3,
)
print(r.choices[0].message.content)          # or r.output_text
print(r.model, r.usage.total_tokens, r.latency)   # r.model tells you which provider/model really answered
```

Migrating from OpenAI is a one-line change: construct `LLMF()` instead of `OpenAI()`.

## Python API

```python
import llmf

llmf.chat("Hello")                                              # -> str-like Reply (.provider .model .reasoning)
for piece in llmf.stream("Count from 1 to 5"): print(piece, end="")
s = llmf.session(system="Be brief"); s("My name is An"); s("What is my name?")   # keeps history
reply = await llmf.achat("hi")                                  # async
```

```python
llm.chat.completions.create(model="best", ...)                  # intent: fast | best | code | vision | reasoning
llm.chat.completions.create(model="ovh/Qwen3.5-397B-A17B", ...) # exact: provider/model
llm.chat.completions.create(model="qwen", ...)                  # fuzzy name
llm.chat.completions.create(model=["best", "fast"], ...)        # ordered list
llm.chat.completions.create(provider="ovh", ...)                # provider default model
llm.models.resolve("fast")                                      # what does this name expand to?
llm.chat.completions.create(model="vision", messages=[{"role": "user", "content": [
    {"type": "text", "text": "What is in this picture?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}])
```

Add your own OpenAI-compatible endpoint: `llm.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)`.

## Configuration

```python
llm = LLMF(
    timeout=30,                        # seconds per request
    deadline=120,                      # total budget for one call, fallbacks included
    proxy="socks5h://127.0.0.1:1080",  # your own proxy
    routing="adaptive",                # "ranked" (fixed order) | "adaptive" (fastest first)
    race=2,                            # ask 2 providers at once, first answer wins (uses quota N times faster)
    exclude=["blockrun"],              # or only=["ovh", "llm7"]
    transport="auto",                  # "urllib" | "auto" | "curl_cffi"
    max_inflight=6,                    # simultaneous requests per provider before spilling over
    vision_timeout=90,
)
```

Every option can also be passed per call. Environment: `LLMF_MODEL`, `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_ROUTING`,
`LLMF_TRANSPORT`, `LLMF_CACHE_DIR`, `LLMF_NO_CACHE=1`.

<details><summary><b>Browser-like transport (optional)</b></summary>

Some endpoints inspect the TLS/HTTP2 fingerprint, which headers cannot change. If `curl_cffi` installs on your machine
(prebuilt wheels, no compiler) use it: `pip install "llmf[stealth]"`, then `LLMF(transport="auto")` or
`LLMF_TRANSPORT=curl_cffi`. If it cannot be installed (some Android/Termux setups) just skip it; llmf behaves exactly as before.
`llmf -v version` shows the active engine.
</details>

## Command line

```bash
llmf "Explain the GIL"                        # also: llmf ask "..."
cat code.py | llmf "Review this" -m code
llmf -p ovh -m qwen3.5-397b --proxy socks5://127.0.0.1:1080 "hi"
llmf chat                                     # interactive (/reset, /exit)
llmf --stream --race 2 --routing adaptive "tell me a joke"
llmf models | doctor | providers | health | serve | version
```

## `llmf doctor`: trust, but verify

The catalogue is a starting point; free endpoints change daily. `doctor` calls **every model once, for real** (providers in parallel):

```bash
llmf doctor                                   # the catalogue
llmf doctor --all                             # + every free chat model each provider lists
llmf doctor --all --include-non-chat          # + guard / whisper / tts / image / video ids (rarely useful)
llmf doctor -p ovh --timeout 20 --json
llmf models                                   # MODEL / TAGS / ALIVE / STATUS
```

```
OK    ovh/gpt-oss-120b                          1.70s  The capital of Vietnam is Hanoi.
FAIL  llm7/codestral-latest                     0.42s  HTTP 429: Rate limit exceeded. Retry after 1 seconds.
```

Results go to `~/.cache/llmf/` (24 h health, last-20 history). A model with ≥ 3 samples and < 50 % success is demoted
automatically. Strictly quota-limited providers (`chatai`) are skipped unless `--include-limited`.
Not sure your environment can reach everything? `python live_test.py` runs ~60 real checks and writes `llmf_live_report.json`.

## `llmf serve`: OpenAI-compatible server

```bash
llmf serve                                    # http://127.0.0.1:8000/v1, local only, no auth
```

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="x")
c.chat.completions.create(model="best", messages=[{"role": "user", "content": "hi"}])
```

- `POST /v1/chat/completions` (streaming supported), `GET /v1/models`, `GET /health`.
- Unknown model names such as `gpt-4o` mean "automatic" (`--strict-models` returns 404); the response `model` field names the real provider/model.
- Load shedding: `--max-concurrent N` (default 48) answers `429 {"code":"busy"}` + `Retry-After: 1` rather than queueing; listen backlog 128.
- Free endpoints rate-limit themselves, so real throughput is theirs, not llmf's. Load-test with a moderate `-c` (5-10).

## Going public

```bash
llmf serve --cloudflare --ui                                   # web chat on a public https URL (needs `cloudflared`)
llmf serve --app "node main.js" --app-port 3000 --cloudflare   # your own Node project + AI
llmf serve --html /sdcard/download/index.html --ui --public    # host one HTML file (and only that file)
llmf serve --public --api-keys-file keys.txt \
           --tls-cert c.pem --tls-key k.pem --allow-ip 203.0.113.0/24   # your own server
```

| Flag | What it does |
|---|---|
| `--public` | Internet profile: binds `0.0.0.0`, API key **required** (one is generated and printed if you give none), rate limits, bans, body/token caps, anti-bot. |
| `--cloudflare` / `--tunnel-token T` | Quick tunnel (random `trycloudflare.com` URL) or your named tunnel, via your own `cloudflared` (Termux: `pkg install cloudflared`). Implies `--public` and `--trust-proxy`. |
| `--ui` | Built-in chat page (streaming, history in `localStorage`, safe text rendering, EN/VI). |
| `--web PATH` / `--html PATH` | Serve one file (nothing else from its folder) or a static directory (no `..`, dotfiles or symlink escape; SPA fallback). |
| `--app "CMD"` `--app-port N` `--app-dir D` | Start your project (receives `$PORT`, `$OPENAI_BASE_URL`, `$OPENAI_API_KEY`), wait until it listens, reverse-proxy it. |
| `--api-key K` (repeatable), `--api-keys-file F` | Bearer keys. |
| `--rate`, `--ip-rate`, `--session-rate` | Requests/min per key, per IP, per web visitor. |
| `--allow-ip`, `--deny-ip` | CIDR lists (repeatable). |
| `--trust-proxy` | Read the client IP from `CF-Connecting-IP` / `X-Forwarded-For`, **only from a loopback peer**. |
| `--cors`, `--cors-origin O` | All origins, or an allow-list. |
| `--max-body`, `--max-tokens-cap`, `--max-concurrent` | Size and concurrency caps. |
| `--tls-cert`, `--tls-key` | HTTPS (TLS ≥ 1.2) with HSTS. |
| `--antibot pow\|turnstile\|off`, `--pow-bits N`, `--turnstile-secret/--turnstile-sitekey` | Visitor check for web pages. |
| `--log-file F` | JSON-lines access log (`-` = stderr). Prompts and keys are never logged. |
| `--csp POLICY` | `Content-Security-Policy` on every response. |

**Use it from your own page**

```html
<script src="/_llmf/client.js"></script>
<script>
  await llmf.stream([{role: "user", content: "Hello"}], {onDelta: (t, full) => out.textContent = full});
  // also: llmf.chat(messages) -> string, llmf.fetch(url, init) -> fetch() with the session attached
</script>
```

The script solves the proof of work in the background and holds a short-lived session token, so **no API key ever reaches the browser**.
Server-side callers use `Authorization: Bearer <key>`.

## Security model

What `--public` / `--cloudflare` switch on, and what they do **not** do.

- **Authentication**: constant-time key comparison; keys never logged (only a short hash id); repeated failures ban the IP for 15 min.
- **Abuse control**: token-bucket limits per key / IP / visitor, connection cap, socket timeouts, request-size and `max_tokens` caps.
- **Anti-bot**: stateless HMAC-signed proof-of-work challenge (single use, expires in 2 min, difficulty rises for noisy IPs) → session token bound to the client IP, 30 min. Turnstile is verified server-side and **fails closed**. Web sessions cannot send images or tools and get tighter limits than API keys.
- **Web hygiene**: nosniff, no-referrer, frame protection, `Cache-Control: no-store` on API replies, strict CSP on the built-in UI, no HTML injection (text nodes only), no directory listing, no Python version banner, generic error messages (no tracebacks or upstream details).
- **Proxy**: llmf credentials are stripped before forwarding to `--app`; client-supplied `X-Forwarded-*` is replaced; proxy headers are trusted only from loopback, so a LAN neighbour cannot spoof `CF-Connecting-IP`.
- **Not provided**: this is not a WAF or DDoS shield; put Cloudflare (or similar) in front for volumetric attacks. Quick-tunnel URLs change on every run. WebSocket upgrades are not proxied to `--app`. `--app` runs the command *you* give it. Proof of work raises the cost of scripted abuse; it does not make it impossible. Free upstreams still limit total throughput.

Found a vulnerability? Please open a private security advisory on GitHub rather than a public issue.

## Providers

Auto-selected fallback order: `ch-at → rewind-ai → ovh → kilo-openrouter → freeai → chatjimmy → kilo-gateway → pollinations → llm7 → blockrun → chatai`. `nottrack` is opt-in (`provider="nottrack"`).

| Provider | Typical models | Notes |
|---|---|---|
| `ch-at` | `gpt-4o` | No auth, single model, ~100 req/min documented. |
| `rewind-ai` | `qwen-2.5-7b-instruct`, `gpt-4o-mini` | Server-issued anonymous token. |
| `ovh` | `gpt-oss-120b`, `Qwen3.5-397B-A17B`, `Qwen2.5-VL-72B` (vision) | Fast and clean. |
| `kilo-openrouter`, `kilo-gateway` | Nemotron 3 Ultra 550B, north-mini-code, super-vl (vision), `kilo-auto/*` | ~200 req/h/IP; large models are slower. |
| `freeai` | `qwen7b` (Qwen 3.6 35B, vision), `qwen-coder`, `deepseek-r1` | Self-hosted free models; the site's OpenRouter list is paid. |
| `llm7` | `gpt-oss:20b`, `codestral-latest` | Quick; answers 429 under load. |
| `pollinations` | `openai` | 1 request / 15 s. |
| `chatjimmy` | `llama3.1-8B` | Extremely fast, non-streaming, a few requests/IP/day. |
| `blockrun` | Nemotron family, `llama-3.2-11b-vision` | ~12 s upstream timeout; flaky. |
| `chatai` | `claude-haiku-5.5`, `gemini-2.5-flash-lite`, … | Premium but ~3-5 requests/IP/day; last resort. |
| `nottrack` | `debate` | Opt-in; several speakers, use `timeout >= 60`. |

Run `llmf models` for what is alive on *your* network right now.

## Error handling

- Transient errors (network, 5xx, timeout) retry one round; 4xx/429 skip that target.
- `429` with "Retry after N" → provider rests N+1 s; plain `429` → 60 s; capacity errors rest only that model for 10 min; "paid / premium / daily limit" → hours.
- Empty answers, errors hidden inside HTTP 200, `<think>` blocks (moved to `.reasoning`), stray blank lines and ChatJimmy stats are cleaned up.
- Out of options: `llmf.AllProvidersFailed` with `.errors`.

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree && cd llmfree
python -m unittest discover -s tests -v       # offline: fake provider, SOCKS and curl_cffi servers
python tests/browser_ui.py                    # optional: Playwright check of the web chat
```

```
src/llmf/
  client.py        LLMF / Client, sessions, streams, fallback, routing, race, doctor
  registry.py      providers, vetted catalogue, aliases, name resolution
  providers/       builtin catalogue + adapters (OpenAI-compatible, ChatJimmy, ChatAI, NotTrack)
  errors.py        error classification and cooldown policy
  _http.py _curl.py _socks.py   transports (stdlib, optional curl_cffi, SOCKS)
  _cache.py        health + survival history
  server.py        `llmf serve`
  _security.py     rate limiter, bans, CIDR, proof-of-work / Turnstile
  _web.py _tunnel.py  static files, app process + reverse proxy, cloudflared
  web/             built-in chat page and browser client
  cli.py           the `llmf` command
```

See [CHANGELOG.md](CHANGELOG.md). Contributions that add a provider should include a real-network `doctor` result.

## License

MIT © 2026 Html / MoonLite-Br
