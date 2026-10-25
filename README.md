# llmf

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI](https://img.shields.io/badge/PyPI-0.6.2-blue)](https://pypi.org/project/llmf/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**llmf** (*llmfree*) is a **stdlib-only** Python library and CLI for public, no-API-key OpenAI-compatible endpoints. It picks a live target, falls back on failure, and runs on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)                 # Reply is a str subclass
print(r.source)          # "provider/model"
print(r.provider, r.model, round(r.latency, 3), r.usage)
```

---

## Install

```bash
pip install -U llmf
pip install -U "llmf[stealth]"   # optional: curl_cffi TLS fingerprint

python -c "import llmf; print(llmf.__version__)"
llmf version
llmf -v version                  # + active transport
```

### `pip show llmf`

```text
Name: llmf
Version: 0.6.2
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
| **Version** | `0.6.2` |
| **Dependencies** | none (optional: `stealth` → `curl_cffi>=0.7`) |
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

llmf.chat("hi", model="best")          # fast | best | code | vision | reasoning
llmf.chat("hi", model=["best", "fast"])
llmf.chat("hi", provider="ch-at")
llmf.chat("hi", provider="nottrack")   # opt-in (auto=False)
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

### Catalog, survival, concurrency, transport

```python
for m in llmf.models.list():
    print(m.name, m.tags, m.alive, m.samples, m.streaming)

llmf.models.list(live=True)
llmf.models.resolve("fast")
llmf.models.check()                 # doctor → survival history

llmf.configure(
    timeout=30,
    vision_timeout=90,
    routing="adaptive",
    race=2,
    max_inflight=6,                 # per-provider parallel cap before spill
    transport="auto",               # urllib | auto | curl_cffi
    impersonate="chrome",
)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
```

**Env:** `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`, `LLMF_TRANSPORT`, `LLMF_IMPERSONATE`

---

## What’s new (0.6.x)

### 0.6.2
- Packaging release of the load-aware stack with full README / correct project URLs / static badges.

### 0.6.1 (runtime)
- **Load-aware routing** (threads, `race`, `llmf serve`): per-provider concurrency caps (`Client(max_inflight=6)`; e.g. ch-at 8, llm7 3, pollinations 1). Extra work **spills** to the next provider instead of queueing behind a busy one.
- **`llmf serve --max-concurrent N`** (default 48): returns `429 {"code":"busy"}` + `Retry-After: 1` under load; listen backlog 128.
- Friendlier errors for `llmf serve --host 8000` (port-in-host-slot) and “port in use”.

### 0.6.0
- Vetted catalogue (≥2 live runs, ≥75% success).
- Survival history (`history.json`, `alive` / `flaky` / `dead`, `ModelInfo.alive` / `.samples`).
- Optional `llmf[stealth]` / `transport` / `impersonate`.
- `ModelInfo.streaming` / `no-stream` in `llmf models`.

See [CHANGELOG.md](CHANGELOG.md).

---

## Built-in providers

| Provider | Auto | Concurrency note | Notes |
|----------|------|------------------|--------|
| `ch-at` | yes | cap 8 | Early / `best` |
| `rewind-ai` | yes | | Vetted instruct models |
| `ovh` | yes | | Default `gpt-oss-120b` |
| `kilo-openrouter` | yes | | Free OpenRouter-style ids |
| `freeai` | yes | | `qwen7b`, … |
| `chatjimmy` | yes | | Fast; may be non-streaming |
| `kilo-gateway` | yes | | |
| `pollinations` | yes | cap 1 | `openai` |
| `llm7` | yes | cap 3 | |
| `blockrun` | yes | | |
| `chatai` | yes | | Strict daily quota |
| `nottrack` | **no** | | Opt-in: `provider="nottrack"` |

---

## CLI

```text
llmf "question" | llmf ask "…"
llmf chat
llmf models [list|check|resolve NAME]
llmf doctor [--all] [--include-non-chat] [--include-limited] [--no-save]
llmf providers | health | version
llmf serve [--host] [--port] [--max-concurrent N] [--api-key] [--cors]
```

**Flags:** `-m/--model`, `-p/--provider`, `-s/--system`, `--image`, `--stream`, `--json`, `-v`,  
`--routing ranked|adaptive`, `--race N`, `--timeout`, `--proxy`,  
`--transport urllib|auto|curl_cffi`, `--impersonate`,  
`--live`, `--all`, `--include-limited`, `--include-non-chat`, `--no-save`,  
serve: `--host`, `--port`, `--max-concurrent`, `--api-key`, `--cors`, `--strict-models`, `--no-fallback`.

```text
$ llmf -v "2+2=?"
$ llmf models
$ llmf doctor
$ llmf serve --port 8000 --max-concurrent 48
$ llmf --transport auto -v version
```

---

## Behaviour

- Fallback + cooldowns; survival scores demote flaky models.
- Load-aware: at concurrency limit, **spill** to next provider (no long queue on one busy endpoint).
- Live catalog/doctor: chat+free by default.
- `transport="auto"` uses `curl_cffi` when `llmf[stealth]` is installed.
- Total failure → `llmf.AllProvidersFailed`.

---

## Safety

Unofficial free endpoints may change. Do not send secrets. Opt-in providers and `discover()` are explicit. `llmf serve` defaults to localhost.

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
