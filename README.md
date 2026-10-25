# llmf

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/llmf.svg)](https://pypi.org/project/llmf/)

**llmf** (*llmfree*) is a **stdlib-only** Python library and CLI for public, no-API-key OpenAI-compatible endpoints. It selects a live target, falls back on failure, and runs on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)                 # Reply is a str subclass
print(r.source)          # e.g. "ch-at/gpt-4o"
print(r.provider, r.model, round(r.latency, 3), r.usage)
```

---

## Install

```bash
pip install -U llmf
python -c "import llmf; print(llmf.__version__)"
llmf version
```

### `pip show llmf` (example fields)

```text
Name: llmf
Version: <installed version>
Summary: llmf (llmfree): free, keyless LLM chat with automatic multi-provider fallback — stdlib only.
Home-page: https://github.com/MoonLite-Br/llmfree
Author: Html
License: MIT
Requires-Python: >=3.8
Requires: (none)
```

| Field | Value |
|--------|--------|
| **Name** | `llmf` |
| **Requires-Python** | `>=3.8` |
| **Dependencies** | none |
| **License** | MIT |
| **Repository** | https://github.com/MoonLite-Br/llmfree |
| **PyPI** | https://pypi.org/project/llmf/ |

---

## Python API

### Short form → `Reply`

```python
import llmf

r = llmf.chat("Hello!")
assert isinstance(r, str)
r.text            # == str(r)
r.source          # "provider/model"
r.provider
r.model
r.latency         # seconds
r.usage           # dict or None
r.finish_reason
r.reasoning       # optional
r.attempts        # [Attempt(provider, model, ok, latency, error), ...]
```

**`model=`:** aliases `fast` | `best` | `code` | `vision` | `reasoning`, fuzzy names, full `provider/id`, or a list tried in order.

```python
llmf.chat("hi", model="best")
llmf.chat("hi", model=["best", "fast"])
llmf.chat("hi", provider="ch-at")
llmf.chat("hi", provider="nottrack")   # opt-in provider (not in auto chain)
llmf.chat("Describe this", images=["photo.jpg"], model="vision")

for piece in llmf.stream("Count 1 to 5"):
    print(piece, end="", flush=True)
```

Also: `llmf.achat`, `llmf.astream`, `llmf.session(system=...)`.

### OpenAI-shaped form

```python
from llmf import LLMF

llm = LLMF()
c = llm.chat.completions.create(
    model="best",
    messages=[{"role": "user", "content": "Hello"}],
)
print(c.choices[0].message.content)
print(c.model, c.provider, c.usage, c.latency, c.attempts)
```

Streaming: `stream=True` yields chunks with `choices[0].delta.content`.

### Catalog & configuration

```python
llmf.models.list()
llmf.models.list(live=True)                       # chat/free only by default
llmf.models.list(live=True, include_non_chat=True)
llmf.models.resolve("best")
llmf.models.check()                               # live one-shot probe; ~24h cache

llmf.providers.list()
llmf.health.check()

llmf.configure(timeout=30, vision_timeout=90, routing="adaptive", race=2)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
llmf.discover()                                   # opt-in external keyless catalog
```

**Environment:** `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`  
**Proxy:** `http://`, `https://`, `socks5://`, `socks5h://`, `socks4://` (stdlib)

---

## Built-in providers (0.5.x)

| Provider | In auto chain | Notes |
|----------|---------------|--------|
| `ch-at` | yes | Early in chain / `best` (e.g. `gpt-4o`) |
| `rewind-ai` | yes | Qwen / gpt-4o-mini; some sign-in models marked broken |
| `ovh` | yes | Default `gpt-oss-120b` |
| `kilo-openrouter` | yes | Free OpenRouter-style ids |
| `freeai` | yes | `qwen7b`, `qwen-coder`, `deepseek-r1` |
| `chatjimmy` | yes | Fast small model |
| `kilo-gateway` | yes | Gateway free routes |
| `pollinations` | yes | `openai` (alias `openai-fast`) |
| `llm7` | yes | `gpt-oss:20b`, `minimax-m2.7`, … |
| `blockrun` | yes | Default `nemotron-3.5-lightning` |
| `chatai` | yes | Higher-tier models; strict daily quota |
| `nottrack` | **no** (`auto=False`) | Opt-in only: `provider="nottrack"` |

Exact model lists change; use `llmf models` / `llmf providers`.

---

## CLI

```text
usage: llmf [options] "question"              ask once (also reads stdin)
       llmf chat                              interactive chat (/reset, /exit)
       llmf models [list|check|resolve NAME]
       llmf doctor [--all] [--include-non-chat] [--include-limited]
       llmf providers | health
       llmf serve [--port N]
       llmf version
```

| Command | Description |
|---------|-------------|
| `llmf "…"` / `llmf ask "…"` | One-shot ask |
| `llmf chat` | Interactive REPL |
| `llmf models` / `models list` | Catalog |
| `llmf models list --live` | Merge live `/models` (chat/free default) |
| `llmf models resolve best` | Expand alias |
| `llmf models check` / `doctor` | Probe each model once |
| `llmf doctor --all` | Include live-discovered ids |
| `llmf doctor --include-limited` | Quota-limited providers |
| `llmf doctor --include-non-chat` | Non-chat model ids |
| `llmf doctor --no-save` | Do not write health cache |
| `llmf providers` | Provider table |
| `llmf health` | Quick OK/FAIL ping |
| `llmf serve` | Local OpenAI-compatible HTTP server |
| `llmf version` | Print package version |

**Flags:** `-m/--model`, `-p/--provider`, `-s/--system`, `-i/--interactive`, `--image`, `--max-tokens`, `-t/--temperature`, `--stream`, `--json`, `-v`, `--routing ranked|adaptive`, `--race N`, `--timeout`, `--proxy`, `--live`, `--all`, `--include-limited`, `--include-non-chat`, `--no-save`, `--host`, `--port`, `--api-key`, `--cors`, `--strict-models`, `--no-fallback`.

```text
$ llmf -v "2+2=?"
$ llmf models
$ llmf doctor
$ llmf serve --port 8000
```

---

## Behaviour

- Automatic fallback with cooldowns: rate-limit vs capacity vs “paid model” messages differ (see CHANGELOG 0.4.x).
- `routing="adaptive"` (latency EWMA), `race=N` (parallel hedge).
- Live catalog / doctor default to **chat + free** models only.
- Dynamic `fast` tag from measured latency; `vision_timeout` (default 90s) for image calls.
- Providers with `auto=False` (e.g. `nottrack`) never join the default chain.
- Total failure → `llmf.AllProvidersFailed` with `.errors`.

---

## Safety

- Endpoints are unofficial and free; they may change or vanish.
- Do not send secrets or personal data.
- Opt-in providers and `discover()` are explicit.
- `llmf serve` defaults to **127.0.0.1**, no CORS, unless you pass `--cors` / `--api-key`.

---

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree.git
cd llmfree
python -m unittest discover -s tests -v
python -m build && twine check dist/*
```

Full history: [CHANGELOG.md](CHANGELOG.md).

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
