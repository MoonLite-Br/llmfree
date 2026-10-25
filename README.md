# llmf

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**llmf** (*llmfree*) is a **stdlib-only** Python library and CLI for public, no-API-key OpenAI-compatible endpoints. It picks a live target, falls back on errors, and runs on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)           # Reply is a str subclass
print(r.source)    # "provider/model"
```

---

## Package metadata (`pip show llmf`)

```text
Name: llmf
Version: 0.5.0
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

llmf.chat("hi", model="best")          # aliases: fast | best | code | vision | reasoning
llmf.chat("hi", model=["best", "fast"])
llmf.chat("Describe this", images=["photo.jpg"], model="vision")
llmf.chat("…", provider="ch-at")       # force a provider (incl. opt-in ones)

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

### Catalog & config

```python
llmf.models.list()
llmf.models.list(live=True)                              # chat/free by default
llmf.models.list(live=True, include_non_chat=True)
llmf.models.resolve("best")
llmf.models.check()
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
llmf serve [--port 8000] [--api-key …] [--cors]
```

Flags: `-m/--model`, `-p/--provider`, `-s/--system`, `--image`, `--stream`, `--json`, `-v`, `--routing`, `--race`, `--timeout`, `--proxy`, `--live`, `--all`, `--include-non-chat`, …

```text
$ llmf -v "2+2=?"
$ llmf models
$ llmf doctor
$ llmf serve --port 8000
```

---

## What’s new in 0.5.0

- **New providers:** `ch-at` (e.g. GPT-4o, early in chain / `best`), `rewind-ai` (Qwen / gpt-4o-mini; sign-in-only models marked broken), `nottrack` (SSE “debate” adapter — **opt-in only**, not in the automatic chain; use `provider="nottrack"`).
- **`ProviderSpec.auto=False`:** provider stays out of auto-fallback but remains callable with `provider=`.
- BlockRun defaults / models updated; Pollinations `openai-fast` is an alias of `openai`.

Full history: [CHANGELOG.md](CHANGELOG.md).

---

## Safety

Unofficial free endpoints may change or rate-limit. Do not send secrets. Opt-in providers and `discover()` are explicit. `llmf serve` defaults to localhost.

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
