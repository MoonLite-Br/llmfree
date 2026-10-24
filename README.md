# llmf

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**llmf** (*llmfree*) is a **stdlib-only** Python library and CLI for public, no-API-key OpenAI-compatible endpoints. It picks a live target, falls back on errors, and runs on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)              # Reply is a str subclass
print(r.source)       # "provider/model"
print(r.provider, r.model, round(r.latency, 3), r.usage)
```

---

## Package metadata (`pip show llmf`)

```text
Name: llmf
Version: 0.4.1
Summary: llmf (llmfree): free, keyless LLM chat with automatic multi-provider fallback — stdlib only.
Home-page: https://github.com/MoonLite-Br/llmfree
Author: Html
License: MIT
Requires-Python: >=3.8
Requires:
```

```bash
pip install -U llmf
pip show llmf
```

---

## Install

```bash
pip install -U llmf
python -c "import llmf; print(llmf.__version__)"
llmf version
```

---

## Python API

### Short form → `Reply`

```python
import llmf

r = llmf.chat("Hello!")
r.text, r.source, r.provider, r.model, r.latency, r.usage, r.attempts
```

**`model=` aliases:** `fast` | `best` | `code` | `vision` | `reasoning`  
Also fuzzy names, full `provider/id`, or a list tried in order.

```python
llmf.chat("hi", model="code", max_tokens=256)
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
```

### Catalog & config

```python
llmf.models.list()
llmf.models.list(live=True)                 # chat/free only by default
llmf.models.list(live=True, include_non_chat=True)
llmf.models.resolve("fast")
llmf.models.check()                         # doctor; ~24h cache
llmf.providers.list()
llmf.health.check()
llmf.configure(timeout=30, vision_timeout=90, routing="adaptive", race=2)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
```

Env: `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`.

---

## CLI

```text
llmf "question" | llmf ask "…"
llmf chat
llmf models [list|check|resolve NAME]
llmf doctor [--all] [--include-non-chat] [--include-limited] [--no-save]
llmf providers | health | version
llmf serve [--host 127.0.0.1] [--port 8000] [--api-key …] [--cors]
```

Flags: `-m/--model`, `-p/--provider`, `-s/--system`, `--image`, `--max-tokens`, `-t/--temperature`, `--stream`, `--json`, `-v`, `--routing ranked|adaptive`, `--race N`, `--timeout`, `--proxy`, `--live`, `--all`, `--include-limited`, `--include-non-chat`, `--no-save`, serve options (`--strict-models`, `--no-fallback`, …).

```text
$ llmf -v "2+2=?"
$ llmf models
$ llmf doctor
$ llmf serve --port 8000
```

---

## What’s new in 0.4.1

- Capacity vs “paid model” messages on BlockRun: capacity wins (≈10 min sleep), not hours.
- `Retry after N seconds` → cooldown ≈ 3×N (not flat 60s); llm7 `min_interval=1.1`.
- OVH default model → `gpt-oss-120b` (faster anonymous tier).
- Live-id filter drops more freeai utility models (madlad, realesrgan, rmbg, …).

See [CHANGELOG.md](CHANGELOG.md) for 0.4.0 behaviour (429 classes, chat/free live catalog, dynamic `fast`, `vision_timeout`).

---

## Safety

Unofficial free endpoints may change or rate-limit. Do not send secrets. `discover()` is opt-in. `llmf serve` defaults to localhost.

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
