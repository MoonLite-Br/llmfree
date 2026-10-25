# llmf 

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg?cacheSeconds=300)](https://pypi.org/project/llmf/)
[![llmf 0.6.0](https://img.shields.io/badge/llmf-0.6.0-blue)](https://pypi.org/project/llmf/0.6.0/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg?cacheSeconds=300)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**llmf** (*llmfree*) is a **stdlib-only** Python library and CLI for public, no-API-key OpenAI-compatible endpoints. It picks a live target, falls back on failure, and runs on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)              # Reply is a str subclass
print(r.source)       # "provider/model"
print(r.provider, r.model, round(r.latency, 3), r.usage)
```

---

## Install

```bash
pip install -U llmf
# optional browser-like TLS fingerprint (still works without it):
pip install -U "llmf[stealth]"

python -c "import llmf; print(llmf.__version__)"
llmf version
llmf -v version          # also prints active transport
```

### `pip show llmf`

```text
Name: llmf
Version: <installed>     # currently 0.6.0
Summary: free, keyless LLM chat with automatic multi-provider fallback — stdlib only
Home-page: https://github.com/MoonLite-Br/llmfree
Author: Html
License: MIT
Requires-Python: >=3.8
Requires: (none)
```

| Field | Value |
|--------|--------|
| **Name** | `llmf` |
| **Version** | `0.6.0` |
| **Dependencies** | none (optional extra: `stealth` → `curl_cffi`) |
| **License** | MIT |
| **Repository** | https://github.com/MoonLite-Br/llmfree |
| **PyPI** | https://pypi.org/project/llmf/ |

---

## Python API

### Short form → `Reply`

```python
import llmf

r = llmf.chat("Hello!")
r.text, r.source, r.provider, r.model, r.latency, r.usage, r.attempts

llmf.chat("hi", model="best")       # aliases: fast | best | code | vision | reasoning
llmf.chat("hi", model=["best", "fast"])
llmf.chat("hi", provider="ch-at")
llmf.chat("hi", provider="nottrack")  # opt-in (auto=False)
llmf.chat("Describe this", images=["photo.jpg"], model="vision")

for piece in llmf.stream("Count 1 to 5"):
    print(piece, end="", flush=True)
```

### OpenAI-shaped form

```python
from llmf import LLMF

llm = LLMF()
c = llm.chat.completions.create(
    model="best",
    messages=[{"role": "user", "content": "Hello"}],
)
print(c.choices[0].message.content)
print(c.model, c.provider, c.usage, c.latency)
```

### Catalog, survival stats, config

```python
for m in llmf.models.list():
    print(m.name, m.tags, m.alive, m.samples, m.streaming)

llmf.models.list(live=True)                 # chat/free by default
llmf.models.list(live=True, include_non_chat=True)
llmf.models.resolve("fast")
llmf.models.check()                         # doctor; appends survival history

llmf.providers.list()
llmf.health.check()

llmf.configure(
    timeout=30,
    vision_timeout=90,
    routing="adaptive",
    race=2,
    transport="auto",          # urllib | auto | curl_cffi
    impersonate="chrome",
)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
```

**Environment:** `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`, `LLMF_TRANSPORT`, `LLMF_IMPERSONATE`  
**Proxy:** `http://`, `https://`, `socks5://`, `socks5h://`, `socks4://`

---

## What’s new in 0.6.0

- **Vetted catalogue** — models kept only if they passed ≥2 independent live runs with ≥75% success; weak/sign-in/capacity models removed from the static catalog (uncatalogued `provider/model` ids still work; use `llmf models --live`).
- **Survival history** — each `doctor` run appends to `history.json` (last 20 samples per model). `llmf models` shows `alive 7/7`, `flaky 2/3`, `dead 0/3`. Models with ≥3 samples and &lt;50% success sink to the end of plans. Exposed as `ModelInfo.alive` / `.samples`.
- **Optional stealth transport** — `transport="auto"|"curl_cffi"`, `impersonate="chrome"`, CLI `--transport` / `--impersonate`, env `LLMF_TRANSPORT` / `LLMF_IMPERSONATE`. Install with `pip install "llmf[stealth]"` (`curl_cffi`). Default remains stdlib urllib.
- **Streaming metadata** — `ModelSpec.streams` / `ModelInfo.streaming`; e.g. chatjimmy may show `no-stream`.
- Tag refresh (`fast`, `vision`, `reasoning`); milder “Retry after N” cooldown (N+1 s).

Full history: [CHANGELOG.md](CHANGELOG.md).

---

## Built-in providers (auto chain unless noted)

| Provider | Auto | Notes |
|----------|------|--------|
| `ch-at` | yes | Early / `best` (e.g. `gpt-4o`) |
| `rewind-ai` | yes | Vetted instruct models |
| `ovh` | yes | Default `gpt-oss-120b` |
| `kilo-openrouter` | yes | Free OpenRouter-style ids |
| `freeai` | yes | `qwen7b`, `qwen-coder`, `deepseek-r1` |
| `chatjimmy` | yes | Fast; may be non-streaming |
| `kilo-gateway` | yes | Gateway free routes |
| `pollinations` | yes | `openai` |
| `llm7` | yes | e.g. `gpt-oss:20b`, `codestral-latest` |
| `blockrun` | yes | e.g. `nemotron-3.5-lightning` |
| `chatai` | yes | Higher-tier; strict daily quota |
| `nottrack` | **no** | Opt-in only: `provider="nottrack"` |

Exact lists change with vetting — always check `llmf models` / `llmf doctor`.

---

## CLI

```text
usage: llmf [options] "question"
       llmf chat
       llmf models [list|check|resolve NAME]
       llmf doctor [--all] [--include-non-chat] [--include-limited]
       llmf providers | health
       llmf serve [--port N]
       llmf version
```

| Command | Description |
|---------|-------------|
| `llmf "…"` / `ask` | One-shot ask |
| `llmf chat` | Interactive REPL |
| `llmf models` / `list` | Catalog + **ALIVE** column |
| `llmf models list --live` | Merge live `/models` |
| `llmf models resolve fast` | Expand alias |
| `llmf models check` / `doctor` | Probe models; updates survival history |
| `llmf providers` / `health` | Endpoints / quick ping |
| `llmf serve` | Local OpenAI-compatible server |
| `llmf -v version` | Version + active transport |

**Flags:** `-m/--model`, `-p/--provider`, `-s/--system`, `--image`, `--stream`, `--json`, `-v`, `--routing ranked|adaptive`, `--race N`, `--timeout`, `--proxy`, `--transport urllib|auto|curl_cffi`, `--impersonate`, `--live`, `--all`, `--include-limited`, `--include-non-chat`, `--no-save`, serve: `--host`, `--port`, `--api-key`, `--cors`, `--strict-models`, `--no-fallback`.

```text
$ llmf -v "2+2=?"
$ llmf models
$ llmf doctor
$ llmf --transport auto -v version
$ llmf serve --port 8000
```

---

## Behaviour

- Automatic fallback with cooldowns (rate-limit / capacity / paid differ).
- Survival scores demote chronically failing models in planning.
- Live catalog / doctor default to **chat + free** only (`--include-non-chat` to override).
- `transport="auto"` uses `curl_cffi` when the extra is installed, else urllib.
- Total failure → `llmf.AllProvidersFailed` with `.errors`.

---

## Safety

Unofficial free endpoints may change or vanish. Do not send secrets. Opt-in providers and `discover()` are explicit. `llmf serve` defaults to localhost.

---

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree.git
cd llmfree
python -m unittest discover -s tests -v
python -m build && twine check dist/*
```

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
