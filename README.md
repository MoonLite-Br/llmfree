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
pip install -U llmf                  # everything: library, CLI, local + internet-facing server (stdlib only)
pip install -U "llmf[stealth]"       # optional: + curl_cffi (browser-like TLS fingerprint)
```
One package, no Flask. Quote the brackets in Termux/zsh.

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
| **`llmf serve`** | OpenAI-compatible HTTP server for any app, extension or addon. It can be hardened and exposed to the internet (`--public`, `--cloudflare`). |
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
- **Local safety**: loopback servers refuse foreign `Host` headers (DNS rebinding) and cross-site `Origin`s; only `http(s)` URLs are fetched; responses, stream lines and stream duration are capped; remote text is stripped of terminal escapes.
- **Proxy**: llmf credentials are stripped before forwarding to `--app`; client-supplied `X-Forwarded-*` is replaced; proxy headers are trusted only from loopback, so a LAN neighbour cannot spoof `CF-Connecting-IP`.
- **Not provided**: this is not a WAF or DDoS shield; put Cloudflare (or similar) in front for volumetric attacks. Quick-tunnel URLs change on every run. WebSocket upgrades are not proxied to `--app`. `--app` runs the command *you* give it. Proof of work raises the cost of scripted abuse; it does not make it impossible. Free upstreams still limit total throughput.

Found a vulnerability? Please open a private security advisory on GitHub rather than a public issue.

## Providers

Auto-selected fallback order: `ch-at → rewind-ai → ovh → kilo-openrouter → freeai → chatjimmy → kilo-gateway → pollinations → llm7 → blockrun → chatai`. `nottrack`, `notrack-ai` and `apifreellm` are opt-in (`provider="..."`).

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
| `nottrack` | `debate` | Opt-in (`nottrack.com`); several speakers, use `timeout >= 60`. |
| `notrack-ai` | `notrack-uncensored` | Opt-in (`notrack.ai`); anonymous, uncensored, quality varies; `persona="concise\|normal\|detailed\|creative"`; fresh chat per call. |
| `apifreellm` | `apifree-community` | Opt-in; community tier, stateless single-turn, plain text, ~7 s; limited per IP (llmf spaces calls 21 s, even across commands). |

Run `llmf models` for what is alive on *your* network right now.

## Error handling

- Transient errors (network, 5xx, timeout) retry one round; 4xx/429 skip that target.
- `429` with "Retry after N" → provider rests N+1 s; plain `429` → 60 s; capacity errors rest only that model for 10 min; "paid / premium / daily limit" → hours.
- Empty answers, errors hidden inside HTTP 200, `<think>` blocks (moved to `.reasoning`), stray blank lines and ChatJimmy stats are cleaned up.
- Out of options: `llmf.AllProvidersFailed` with `.errors`.

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree && cd llmfree
pip install -e .
```

```
src/llmf/
  client.py        LLMF / Client, sessions, streams, fallback, routing, race, doctor
  registry.py      providers, vetted catalogue, aliases, name resolution
  providers/       builtin catalogue + adapters (OpenAI-compatible, ChatJimmy, ChatAI, NotTrack)
  errors.py        error classification and cooldown policy
  _http.py _curl.py _socks.py   transports (stdlib, optional curl_cffi, SOCKS)
  _cache.py        health + survival history
  server.py        `llmf serve`: local and --public server, web chat, static/app hosting
  _security.py     limits, bans, IP rules, PoW / Turnstile
  _web.py _tunnel.py   static site + app proxy, Cloudflare tunnel
  web/             chat page + browser client
  cli.py           the `llmf` command
```

Contributions that add a provider should include a real-network `doctor` result.

## Changelog

## 0.7.7
- Docs: full changelog is now inlined in README so it appears on the PyPI project page
  (the relative `CHANGELOG.md` link was not resolvable there).

## 0.7.6
- `llmf serve` validates its options and fails with a one-line error (exit code 2) instead of a traceback or a
  misleading message: `--port` outside 0-65535, unreadable TLS certificate/key, `--tls-key` without `--tls-cert`,
  negative limits, `--max-body 0`, and `--pow-bits` outside 8-28 (99 bits made the web chat unsolvable).
- Cross-process pacing: a slower thread or process can no longer write an older slot over a newer one.

## 0.7.5 (one package again, serve error fix)
- **No more `llmf[serve]`.** The internet-facing server (`--public`, `--cloudflare`, `--ui`, `--html`, `--app`,
  anti-bot, rate limits, bans, IP rules, TLS, access log) is part of `pip install llmf` again, still stdlib-only.
  The separate `llmf-serve` package is retired (it is no longer needed and is not published from this release);
  `pip install "llmf[serve]"` still resolves but now only installs `llmf` (pip warns the extra does not exist).
- **Fixed: `AttributeError: 'Handler' object has no attribute '_sent'`** (and `headers`) in the server when a client sent
  a malformed request (bad request line, unsupported method such as TRACE/CONNECT, oversized URI or header, too many
  headers, bad HTTP version). The connection died with a traceback in the log instead of an HTTP error. Such requests
  now get a small JSON error and the connection is closed; header values are always converted to `str`.
- Tests: raw-socket malformed-request suite for the local, keyed and public servers.

## 0.7.4 (security and robustness audit)
- **Local server vs. web pages**: `llmf serve` (both the core and `llmf-serve`) now refuses DNS-rebinding (a foreign
  `Host` on a loopback-bound server) and cross-site browser requests (an `Origin` that is neither allowed by
  `--cors` / `--cors-origin` nor the server itself). curl and the OpenAI SDKs send no `Origin` and are unaffected.
  Also: a negative `Content-Length` is rejected (it used to read until the client closed), non-object JSON bodies
  give 400, the core server has a socket timeout and no longer announces the Python version.
- **Network hygiene**: only `http(s)` URLs are ever opened (a `file://` URL in a discovery listing could be read);
  responses are capped at 32 MB, also after gunzip (zip bombs); stream lines are capped at 1 MB with a 15-minute
  wall-clock limit (an endless or dripping stream is cut off and the next provider is tried).
- **Discovery** (`stillworks`) keeps only public http(s) hosts: loopback, LAN, link-local, `.local`, credentials in the
  URL and odd model ids are dropped, so a stranger's listing cannot aim llmf at your own network.
- **Untrusted text**: control / escape characters are stripped from every remote error message and model id
  (terminal-escape injection); proxy passwords are never echoed in error messages.
- **Robustness**: a malformed upstream answer (e.g. `choices` that is not an object) is a normal provider failure that
  falls back, not an `AttributeError`; any unexpected adapter exception is contained per attempt; the docs-agent tool
  tolerates non-object answers and URL-quotes the thread id; a tampered `pace.json` cannot stall the client;
  SOCKS5 rejects over-long credentials / host names.
- CI runs with read-only token permissions.

## 0.7.3
- Real-network `doctor` confirmed `notrack-ai/notrack-uncensored` (8.7 s) and `apifreellm/apifree-community` (7.1 s); streaming works on `notrack-ai`.
- **Pacing now survives between processes**: providers with a minimum gap >= 5 s (`apifreellm` 21 s, `pollinations` 15 s)
  record their last slot in `~/.cache/llmf/pace.json`, so two `llmf` commands in a row wait instead of hitting
  "429 Please wait 20 seconds". (`LLMF_NO_CACHE=1` turns it off.)
- CLI: `--persona concise|normal|detailed|creative` (for `notrack-ai`).

## 0.7.2
- Two new **opt-in** providers (never in the automatic chain; low quality, tight limits), models keep the server's own names:
  - `notrack-ai` (`notrack.ai`): model `notrack-uncensored`. Anonymous SSE chat with an automatic cookie bootstrap
    (`GET /chat`, refreshed every 10 min or on 401/403); every call is a fresh chat, history is flattened into one
    `user_input`; `persona="concise|normal|detailed|creative"` as a call keyword. Not the same service as `nottrack`
    (`nottrack.com`).
  - `apifreellm` (`apifreellm.com`): model `apifree-community`. Plain-text community endpoint, stateless single-turn,
    ignores every option, answers in one piece (4-9 s). Limit 5 requests / 20 s / IP: llmf spaces calls 21 s apart and
    now understands "Please wait N seconds" (provider rests N+1 s instead of a flat 60 s).
  - Use them with `provider="notrack-ai"` / `provider="apifreellm"`; `llmf doctor` checks them.


## 0.7.1 (retired split, see 0.7.5)
- **Split into two packages.** `pip install llmf` is the lean core: library, CLI and the basic local `llmf serve`
  (localhost, optional single API key, CORS, load shedding). The internet-facing features of 0.7.0 moved to the optional
  **`llmf-serve`** package (same repo, `serve/`): `--public`, `--cloudflare`, anti-bot, rate limits / bans / IP rules, TLS,
  `--ui`, `--html`/`--web`, `--app`, access log. Install with `pip install "llmf[serve]"`; the core delegates to it
  automatically and prints that exact command if it is missing.
- Extras: `llmf[serve]`, `llmf[stealth]` (`curl_cffi`), `llmf[all]`. Both packages are stdlib-only apart from `curl_cffi`;
  no Flask. Quote the brackets in Termux/zsh.
- Upgrading from 0.7.0: the advanced flags now need `pip install "llmf[serve]"`; everything else is unchanged.
- CI tests the core alone and core + serve; `publish.yml` publishes `llmf` first, then `llmf-serve`
  (a Trusted Publisher must be added on PyPI for both projects).

## 0.7.0
- Catalogue: removed `ovh/Mistral-Nemo-Instruct-2407`, `kilo-openrouter/liquid/lfm-2.5-2.6b:free` and
  `kilo-openrouter/poolside/laguna-s-2.1:free` (404 in the latest real-network `doctor`, 0/3 alive).
- Hardening: proxy headers (`CF-Connecting-IP`, `X-Forwarded-*`) are trusted only from a **loopback** peer (a LAN
  neighbour can no longer spoof its IP behind `--cloudflare`); public profile caps simultaneous connections
  (`max_connections`, default 256); TLS probes on a plain port no longer print tracebacks.
- Docs: README rewritten (English) + `README.vi.md`; project URLs point to MoonLite-Br/llmfree.
- **`llmf serve --public`**: internet-facing profile. Binds `0.0.0.0`, makes an API key mandatory (one is generated and
  printed if you give none), turns on per-key / per-IP rate limits (token bucket, `429` + `Retry-After`), a temporary ban
  after repeated bad keys, body / `max_tokens` caps, security headers (nosniff, no-referrer, X-Frame-Options, HSTS on TLS),
  socket timeouts, generic error messages (no tracebacks, no upstream details, no Python version) and the anti-bot check.
- More flags: repeatable `--api-key` + `--api-keys-file`, `--rate`, `--ip-rate`, `--session-rate`, `--allow-ip` / `--deny-ip`
  (CIDR), `--trust-proxy` (CF-Connecting-IP / X-Forwarded-For, only from a local proxy), `--cors-origin` (allow-list),
  `--max-body`, `--max-tokens-cap`, `--tls-cert/--tls-key`, `--log-file` (JSON lines; prompts and keys are never logged), `--csp`.
- **Anti-bot** for web pages: `--antibot pow` (default when public; stateless HMAC proof of work solved in the browser,
  IP-bound short-lived session token, replay protection, difficulty rises for noisy IPs) or `--antibot turnstile`
  (Cloudflare Turnstile verified server-side, fail-closed). Web sessions are tighter than API keys: no images / tools,
  40 messages, 24k chars, `max_tokens` 1024, own rate limit. Browser helper at `/_llmf/client.js` (`llmf.chat()`, `llmf.stream()`, `llmf.fetch()`).
- **`--ui`**: built-in chat page (streaming, history in localStorage, rendered with text nodes only: no HTML injection).
- **`--web PATH` (alias `--html`)**: serve one HTML file (only that file, never its folder) or a static directory
  (no `..`, no dotfiles, no symlink escape, SPA fallback).
- **`--app "node main.js"`** (+ `--app-port`, `--app-dir`): runs your web project as a child process (gets `$PORT`,
  `$OPENAI_BASE_URL`, `$OPENAI_API_KEY`) and reverse-proxies to it, behind the same IP rules and limits.
- **`--cloudflare`** / `--tunnel-token`: uses your own `cloudflared` (quick tunnel, or a named one) and prints the public URL.

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

## License

MIT © 2026 Html / MoonLite-Br
