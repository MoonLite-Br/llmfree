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
Version: 0.5.0
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
| **Version** | `0.5.0` |
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
Also fuzzy names, full `provider/id`, a list tried in order, or `provider="…"`.

```python
llmf.chat("hi", model="code", max_tokens=256, temperature=0.3)
llmf.chat("hi", model=["best", "fast"])
llmf.chat("Describe this", images=["photo.jpg"], model="vision")  # vision_timeout default 90s
llmf.chat("…", provider="ch-at")       # force provider (works for opt-in too)
llmf.chat("…", provider="nottrack")    # opt-in provider (not in auto chain)

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
llmf.models.list()
llmf.models.list(live=True)                              # chat/free only by default
llmf.models.list(live=True, include_non_chat=True)
llmf.models.resolve("best")
llmf.models.check()                                      # real call per model; ~24h cache
llmf.providers.list()
llmf.health.check()

llmf.configure(timeout=30, vision_timeout=90, routing="adaptive", race=2)
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
llmf.discover()                                          # opt-in external catalog
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

| Command | Description |
|---------|-------------|
| `llmf "…"` / `llmf ask "…"` | One-shot ask |
| `llmf chat` | Interactive REPL |
| `llmf models` / `models list` | Catalog table |
| `llmf models list --live` | + live `/models` (chat/free by default) |
| `llmf models list --live --include-non-chat` | Include non-chat ids |
| `llmf models resolve best` | Expand alias |
| `llmf models check` / `llmf doctor` | Probe models once |
| `llmf doctor --all` | Also live-discovered ids |
| `llmf doctor --include-limited` | Strict daily-quota providers |
| `llmf doctor --include-non-chat` | Non-chat model ids |
| `llmf doctor --no-save` | Skip health cache write |
| `llmf providers` | Provider table |
| `llmf health` | Quick OK/FAIL ping |
| `llmf serve` | Local OpenAI-compatible server |
| `llmf version` | Print version |

**Flags:** `-m/--model`, `-p/--provider`, `-s/--system`, `-i/--interactive`, `--image`, `--max-tokens`, `-t/--temperature`, `--stream`, `--json`, `-v`, `--routing ranked|adaptive`, `--race N`, `--timeout`, `--proxy`, `--live`, `--all`, `--include-limited`, `--include-non-chat`, `--no-save`, `--host`, `--port`, `--api-key`, `--cors`, `--strict-models`, `--no-fallback`.

```text
$ llmf "Say hi in one short sentence."
$ llmf -v "2+2=?"
$ llmf --json "Say hi in one short sentence."
$ llmf models
$ llmf models resolve fast
$ llmf doctor
$ llmf serve --port 8000
```

---

## What’s new in 0.5.0

- **Providers:** `ch-at` (early in chain / `best`), `rewind-ai` (Qwen / gpt-4o-mini; sign-in-only marked broken), `nottrack` (SSE debate adapter — **opt-in only**, not in automatic fallback; use `provider="nottrack"`).
- **`ProviderSpec.auto=False`:** stays out of the auto chain, still usable with `provider=`.
- BlockRun / Pollinations catalogue tweaks (`openai-fast` ≡ `openai`).

Earlier (0.4.x): smarter 429 classes, chat/free-only live catalog by default, dynamic `fast` tag, `vision_timeout`, Retry-After scaling — see [CHANGELOG.md](CHANGELOG.md).

---

## Behaviour notes

- Fallback prefers faster/cleaner targets; failures get cooldowns (rate-limit / capacity / paid messages differ).
- `routing="adaptive"` uses latency EWMA; `race=N` hedges parallel requests.
- `doctor` / `models.check()` results cached ~24h.
- Total failure → `llmf.AllProvidersFailed` with `.errors`.

---

## Safety

- Endpoints are unofficial and free; they may change or vanish.
- Do not send secrets or personal data.
- Opt-in providers (`nottrack`) and `discover()` are explicit.
- `llmf serve` defaults to **localhost**, no CORS, unless you pass `--cors` / `--api-key`.

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
