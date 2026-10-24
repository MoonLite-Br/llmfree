# llmf

**Free, keyless LLM access in one call — with automatic fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/llmf.svg)](https://pypi.org/project/llmf/)

**llmf** (*llmfree*) is a tiny Python library and CLI that talks to **public, no-API-key** OpenAI-compatible endpoints. It picks a working provider, falls back when one fails, and needs **zero third-party dependencies** (stdlib only). Runs on Linux, macOS, Windows, and **Termux**.

```python
import llmf

print(llmf.chat("Explain the CAP theorem in two sentences."))
```

No signup. No keys. Same `Reply` / OpenAI-shaped objects every time.

---

## Package info (`pip show llmf`)

| Field | Value |
|--------|--------|
| **Name** | `llmf` |
| **Version** | `0.3.0` |
| **Summary** | Free, keyless LLM chat with automatic multi-provider fallback — stdlib only |
| **Author** | Html |
| **License** | MIT |
| **Requires-Python** | `>=3.8` |
| **Dependencies** | *none* |
| **Home-page** | https://github.com/MoonLite-Br/llmfree |
| **PyPI** | https://pypi.org/project/llmf/ |

```bash
pip show llmf
pip show -f llmf    # list installed files
```

---

## Install

```bash
pip install -U llmf
```

Verify:

```bash
python -c "import llmf; print(llmf.__version__)"
llmf version
```

---

## Quick start

### Simple API

```python
import llmf

llmf.chat("Hello!")
llmf.chat("Write fibonacci in Python", model="code")
llmf.chat("hi", model="fast")          # aliases: fast | best | code | vision | reasoning
llmf.chat("hi", model="llama")         # fuzzy name
llmf.chat("hi", model="ovh/Meta-Llama-3.3-70B-Instruct")
llmf.chat("hi", model=["best", "fast"])

llmf.chat(
    "Return JSON with keys name and age",
    system="Only valid JSON",
    max_tokens=256,
    temperature=0.2,
    json=True,
)

llmf.chat("Describe this", images=["photo.jpg"], model="vision")

for chunk in llmf.stream("Count 1 to 5"):
    print(chunk, end="", flush=True)
```

`chat()` returns a **`Reply`**: acts like a `str`, plus provider/model/attempt metadata.

### OpenAI-shaped API (0.3+)

```python
from llmf import LLMF

llm = LLMF()
r = llm.chat.completions.create(
    model="best",
    messages=[{"role": "user", "content": "Hello"}],
)
print(r.choices[0].message.content)
print(r.usage)

# Streaming
for event in llm.chat.completions.create(model="fast", messages=[...], stream=True):
    ...
```

Module helpers still work: `llmf.chat(...)`, `llmf.models()`, `llmf.providers()`, `llmf.health()`.

```python
llmf.models.list()
llmf.models.check()       # doctor: real call per model (cached ~24h)
llmf.models.resolve("fast")
llmf.providers.list()
llmf.health.check()
```

---

## CLI

```text
llmf "Your question"                 # one-shot ask
llmf ask "..." -m best --stream
llmf chat                            # interactive (/reset, /exit)
llmf models                          # catalog
llmf models list
llmf models resolve fast
llmf models check                    # live probe + health cache
llmf doctor [--all] [--include-limited]
llmf providers
llmf health
llmf serve [--port 8000] [--api-key SECRET]
llmf version
```

Useful flags: `-m/--model`, `-p/--provider`, `-s/--system`, `--image`, `--max-tokens`, `-t/--temperature`, `--stream`, `--json`, `--routing ranked|adaptive`, `--race N`, `--proxy URL`.

Local OpenAI-compatible server (default `127.0.0.1`, no CORS):

```bash
llmf serve --port 8000
curl http://127.0.0.1:8000/v1/models
```

Bind `0.0.0.0` only together with `--api-key`.

---

## Configuration

| Mechanism | Examples |
|-----------|----------|
| **Code** | `llmf.configure(timeout=30, exclude=["blockrun"], routing="adaptive", race=2)` |
| **Env** | `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING` |
| **Proxy** | HTTP(S) or SOCKS4/4a/5/5h (stdlib): `proxy="socks5h://127.0.0.1:9050"` |
| **Custom endpoint** | `llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)` |
| **Discovery** | `llmf.discover()` — opt-in scan for extra keyless bases |

Isolated client (no shared state):

```python
from llmf import Client
c = Client(timeout=20, routing="adaptive")
c.chat("hi")
```

---

## How it works

1. Build a **fallback plan** from aliases, explicit ids, and provider health.
2. Prefer fast/clean targets; **cool down** failures (longer on HTTP 429).
3. Optional **`routing="adaptive"`** uses latency EWMA; **`race=N`** hedges parallel requests.
4. **`doctor` / `models.check()`** results are cached (~24h) to demote dead models.
5. Strip thinking/stats noise; treat empty “HTTP 200” bodies as failures.
6. If everything fails → `llmf.AllProvidersFailed` with `.errors` per provider.

Public free endpoints change often — use `llmf health` and `llmf doctor` to see what still works.

---

## Safety

- Endpoints are **unofficial and free**. They may rate-limit, change, or vanish.
- **Do not send secrets**, passwords, or personal data to third-party servers.
- `discover()` contacts external catalogs; treat as opt-in.
- Default `llmf serve` listens on localhost only.

---

## Project links

| | |
|--|--|
| **Source** | https://github.com/MoonLite-Br/llmfree |
| **Issues** | https://github.com/MoonLite-Br/llmfree/issues |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |
| **PyPI** | https://pypi.org/project/llmf/ |
| **License** | [MIT](LICENSE) |

---

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree.git
cd llmfree
python -m unittest discover -s tests -v
python -m build && twine check dist/*
```

Supported Python: **3.8–3.13**.

---

## License

MIT © 2026 Html / MoonLite-Br
