# llmf

**Free, keyless LLM chat in one call.**

[![PyPI](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`llmf` (llmfree) talks to public, no-key OpenAI-compatible endpoints, picks a live one, and **falls back automatically** when something fails. Zero third-party dependencies — stdlib only. Works on desktop, server, and **Termux**.

```python
import llmf

print(llmf.chat("Hello — who are you?"))
```

No API keys. No provider setup. Same return type every time.

---

## Install

```bash
pip install -U llmf
```

Requires **Python ≥ 3.8**.

```bash
python -c "import llmf; print(llmf.__version__)"
llmf version
```

---

## Quick start

```python
import llmf

# Auto provider + model
llmf.chat("Summarize the CAP theorem in two sentences.")

# Intent shortcuts: fast | best | code | vision | reasoning
llmf.chat("Write a Python fibonacci function", model="code")

# Fuzzy or explicit model ids
llmf.chat("hi", model="llama")
llmf.chat("hi", model="ovh/Meta-Llama-3.3-70B-Instruct")

# Try models in order
llmf.chat("hi", model=["best", "fast"])

# Options
llmf.chat(
    "Return a JSON object with keys name and age",
    system="You only output valid JSON",
    max_tokens=300,
    temperature=0.2,
    json=True,
)

# Images (path, URL, or bytes)
llmf.chat("Describe this image", images=["photo.jpg"], model="vision")

# Streaming
for chunk in llmf.stream("Count from 1 to 5"):
    print(chunk, end="", flush=True)
```

`chat()` returns a **`Reply`**: behaves like a `str`, plus metadata (provider, model, attempts, …).

---

## CLI

```bash
llmf "Your prompt here"
llmf chat "Explain recursion" --model best
llmf models              # built-in catalog
llmf models --live       # probe providers (network)
llmf providers
llmf health
llmf version
```

Local OpenAI-compatible proxy (stdlib HTTP server):

```bash
llmf serve --port 8000
# then: curl http://127.0.0.1:8000/v1/models
```

Defaults to `127.0.0.1` only. Use `--host 0.0.0.0` only with `--api-key`. Use `--cors` if a browser extension must call it.

---

## API surface

| Function | Purpose |
|----------|---------|
| `llmf.chat(...)` | One-shot completion → `Reply` |
| `llmf.stream(...)` | Token stream |
| `llmf.achat` / `llmf.astream` | Async wrappers |
| `llmf.session(system=...)` | Multi-turn conversation helper |
| `llmf.models(live=False)` | List models |
| `llmf.providers()` | List providers |
| `llmf.health()` | Quick liveness checks |
| `llmf.register(...)` | Add your own OpenAI-compatible base URL |
| `llmf.discover()` | Opt-in scan for extra keyless endpoints |
| `llmf.configure(...)` | Timeout, proxy, include/exclude providers |
| `llmf.Client(...)` | Isolated client (no shared state) |

Environment (optional):

| Variable | Effect |
|----------|--------|
| `LLMF_TIMEOUT` | Default request timeout (seconds) |
| `LLMF_PROXY` | HTTP(S) proxy for all requests |
| `LLMF_MODEL` | Default model preference |

```python
llmf.configure(timeout=30, exclude=["blockrun"])
llmf.configure(proxy="http://127.0.0.1:8080")
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
```

---

## How fallback works

1. Prefer endpoints that are fast and clean in practice.
2. On failure, cool down that target (e.g. longer after HTTP 429).
3. Strip thinking / stats noise; treat empty “success” bodies as failures.
4. If every target fails → `llmf.AllProvidersFailed` with per-provider `.errors`.

Built-in providers (availability changes over time): ChatJimmy, OVH, FreeAI, LLM7, Kilo/OpenRouter gateway, BlockRun, Pollinations, ChatAI, and others registered in the package. Always verify with `llmf health` / `llmf models --live`.

---

## Safety notes

- These are **public, unofficial, free** endpoints. They can rate-limit, change, or disappear without notice.
- **Do not send secrets**, passwords, or personal data — prompts go to third-party servers.
- `discover()` contacts external catalogs; treat it as opt-in.
- Default local server binds to localhost and disables CORS on purpose.

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

MIT — see [LICENSE](LICENSE).

**PyPI:** [pypi.org/project/llmf](https://pypi.org/project/llmf/) · **Source:** [github.com/MoonLite-Br/llmfree](https://github.com/MoonLite-Br/llmfree)
