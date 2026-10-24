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
Version: 0.4.0
Summary: llmf (llmfree): free, keyless LLM chat with automatic multi-provider fallback — stdlib only.
Home-page: https://github.com/MoonLite-Br/llmfree
Author: Html
Author-email: moonlite-br@users.noreply.github.com
License: MIT
Requires-Python: >=3.8
Requires:
```

| Field | Value |
|--------|--------|
| **Name** | `llmf` |
| **Version** | `0.4.0` |
| **Dependencies** | none |
| **License** | MIT |
| **Repository** | https://github.com/MoonLite-Br/llmfree |
| **PyPI** | https://pypi.org/project/llmf/ |

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
assert isinstance(r, str)
r.text                 # same as str(r)
r.source               # "provider/model"
r.provider, r.model
r.latency              # seconds
r.usage                # dict or None
r.finish_reason
r.reasoning            # optional
r.attempts             # list of Attempt(provider, model, ok, latency, error)
```

**`model=` aliases:** `fast` | `best` | `code` | `vision` | `reasoning`  
Also fuzzy names, full `provider/id`, or a list tried in order.

```python
llmf.chat("hi", model="code", max_tokens=256, temperature=0.3)
llmf.chat("hi", model=["best", "fast"])
llmf.chat("Describe this", images=["photo.jpg"], model="vision")  # uses vision_timeout (default 90s)
llmf.chat("...", json=True)

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
print(c.model, c.provider, c.usage, c.latency, c.attempts)

for chunk in llm.chat.completions.create(
    model="fast",
    messages=[{"role": "user", "content": "Count to 3"}],
    stream=True,
):
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="")
```

### Catalog, doctor, config

```python
llmf.models.list()                          # chat/free catalog by default
llmf.models.list(live=True)                 # merge live /models (still chat/free by default)
llmf.models.list(live=True, include_non_chat=True)  # also TTS/embed/image/guard ids
llmf.models.resolve("fast")
llmf.models.check()                         # real call per model; ~24h cache
llmf.models.check(include_live=True, include_non_chat=False)

llmf.providers.list()
llmf.health.check()

llmf.configure(timeout=30, vision_timeout=90, routing="adaptive", race=2)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
llmf.discover()
```

Env: `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`.  
Proxy: `http://`, `https://`, `socks5://`, `socks5h://`, `socks4://` (stdlib).

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

### Commands

| Command | Description |
|---------|-------------|
| `llmf "…"` / `llmf ask "…"` | One-shot ask |
| `llmf chat` | Interactive REPL |
| `llmf models` / `models list` | Catalog table |
| `llmf models list --live` | + live `/models` (chat/free only by default) |
| `llmf models list --live --include-non-chat` | Include non-chat ids |
| `llmf models resolve fast` | Expand alias |
| `llmf models check` / `llmf doctor` | Probe every chat model once |
| `llmf doctor --all` | Also test live-discovered model ids |
| `llmf doctor --include-limited` | Include strict daily-quota providers |
| `llmf doctor --include-non-chat` | Include non-chat model ids |
| `llmf doctor --no-save` | Do not write health cache |
| `llmf providers` | Provider table |
| `llmf health` | Quick OK/FAIL ping |
| `llmf serve` | Local OpenAI-compatible server |
| `llmf version` | Print version |

### Flags

| Flag | Meaning |
|------|---------|
| `-m` / `--model` | Alias, fuzzy name, or `provider/model` |
| `-p` / `--provider` | Force provider |
| `-s` / `--system` | System prompt |
| `-i` / `--interactive` | REPL |
| `--image PATH` | Image path/URL (repeatable) |
| `--max-tokens` `-t` / `--temperature` | Sampling |
| `--stream` `--json` `-v` | Stream / JSON / show source |
| `--routing ranked\|adaptive` | Fallback strategy |
| `--race N` | Parallel hedged requests |
| `--timeout` `--proxy URL` | Timeout / HTTP(S)/SOCKS proxy |
| `--live` | Live model list |
| `--all` | Doctor: include live ids |
| `--include-limited` | Doctor: quota-limited providers |
| `--include-non-chat` | List/doctor: non-chat models |
| `--no-save` | Doctor: skip cache write |
| `--host` `--port` `--api-key` `--cors` | `serve` bind / auth / CORS |
| `--strict-models` `--no-fallback` | `serve` strictness |

### Examples

```text
$ llmf "Say hi in one short sentence."
Hello! How can I help you today?

$ llmf -v "2+2=?"
ovh/…
4

$ llmf --json "Say hi in one short sentence."
{"text": "…", "provider": "…", "model": "…", "latency": 0.4, ...}

$ llmf models
MODEL                                   TAGS         STATUS
…

$ llmf models resolve fast
…

$ llmf doctor
Testing every model once (providers in parallel)...
OK    …/…   0.90s  Hello…
FAIL  …/…   5.00s  HTTP 429

$ llmf serve --port 8000
# http://127.0.0.1:8000  — /v1/chat/completions, /v1/models, …
```

---

## Behaviour (0.4)

- **429 handling:** plain rate-limit → provider cooldown ~60s; capacity / `ResourceExhausted` → that **model** sleeps ~10 min; “use a paid model” → model sleeps hours.
- **`models.list(live=…)` / `doctor --all`:** default **chat + free only** (skip whisper/tts/embedding/image/video/OCR/guard and priced ids). Override with `include_non_chat=True` / `--include-non-chat`.
- **`fast` tag:** dynamic from measured latency (≤1s joins; failures sink).
- **`vision_timeout`:** default 90s for image requests and vision checks in doctor.
- Fallback + optional `routing="adaptive"` and `race=N`; doctor results cached ~24h.
- Total failure → `llmf.AllProvidersFailed` with `.errors`.

---

## Safety

- Endpoints are unofficial and free; they may change or vanish.
- Do not send secrets or personal data.
- `discover()` is opt-in external catalog access.
- `llmf serve` defaults to **localhost**, no CORS, unless you enable `--cors` / `--api-key`.

---

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree.git
cd llmfree
python -m unittest discover -s tests -v
python live_test.py          # optional live internet report (JSON)
python -m build && twine check dist/*
```

History: [CHANGELOG.md](CHANGELOG.md).

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
