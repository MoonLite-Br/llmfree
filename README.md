# llmf

**Free, keyless LLM access in one call — with automatic multi-provider fallback.**

[![PyPI version](https://img.shields.io/pypi/v/llmf.svg)](https://pypi.org/project/llmf/)
[![Python versions](https://img.shields.io/pypi/pyversions/llmf.svg)](https://pypi.org/project/llmf/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**llmf** (*llmfree*) is a stdlib-only Python library and CLI for **public, no-API-key** OpenAI-compatible endpoints. It chooses a live target, falls back on failure, and works on desktop and **Termux**.

```python
import llmf

r = llmf.chat("Explain the CAP theorem in two sentences.")
print(r)                 # the answer text (Reply is a str subclass)
print(r.source)          # e.g. "ovh/Meta-Llama-3.3-70B-Instruct"
print(r.provider, r.model, r.latency, r.usage)
```

---

## Package metadata (`pip show llmf`)

After `pip install llmf`, you should see fields like:

```text
Name: llmf
Version: 0.3.0
Summary: llmf (llmfree): free, keyless LLM chat with automatic multi-provider fallback — stdlib only.
Home-page: https://github.com/MoonLite-Br/llmfree
Author: Html
Author-email: moonlite-br@users.noreply.github.com
License: MIT
Location: .../site-packages
Requires:
Required-by:
```

| Field | Value |
|--------|--------|
| **Name** | `llmf` |
| **Version** | `0.3.0` |
| **Requires-Python** | `>=3.8` |
| **Dependencies** | *none* |
| **License** | MIT |
| **Repository** | https://github.com/MoonLite-Br/llmfree |
| **PyPI** | https://pypi.org/project/llmf/ |

```bash
pip install -U llmf
pip show llmf
pip show -f llmf
```

---

## Install

```bash
pip install -U llmf
python -c "import llmf; print(llmf.__version__)"
llmf version
```

---

## Python API (0.3)

### 1) Short form — `llmf.chat` → `Reply`

```python
import llmf

r = llmf.chat("Hello!")
# r is a str subclass:
assert isinstance(r, str)
print(r.text)            # same as str(r)
print(r.source)          # "provider/model"
print(r.provider)        # which endpoint answered
print(r.model)
print(r.latency)         # seconds
print(r.usage)           # dict or None (tokens if the upstream sent them)
print(r.finish_reason)
print(r.reasoning)       # optional chain-of-thought if present
print(r.attempts)        # list[Attempt]: provider, model, ok, latency, error
```

Example session (illustrative):

```text
>>> import llmf
>>> r = llmf.chat("Say hi in one short sentence.")
>>> r
Hello! How can I help you today?
>>> r.source
'chatjimmy/...'
>>> r.latency
0.42
>>> [(a.provider, a.ok, round(a.latency, 2)) for a in r.attempts]
[('ovh', False, 1.2), ('chatjimmy', True, 0.42)]
```

**Aliases** for `model=`: `fast` | `best` | `code` | `vision` | `reasoning`  
Also: fuzzy names (`"llama"`), full ids (`"ovh/Meta-Llama-3.3-70B-Instruct"`), or a list tried in order.

```python
llmf.chat("hi", model="code", max_tokens=256, temperature=0.3, system="Be brief")
llmf.chat("hi", model=["best", "fast"])
llmf.chat("Describe this", images=["photo.jpg"], model="vision")
llmf.chat("...", json=True)          # request JSON-style output when supported

for piece in llmf.stream("Count 1 to 5"):
    print(piece, end="", flush=True)
```

### 2) OpenAI-shaped form — `LLMF().chat.completions.create`

```python
from llmf import LLMF

llm = LLMF()
completion = llm.chat.completions.create(
    model="best",
    messages=[{"role": "user", "content": "Hello"}],
)
print(completion.choices[0].message.content)
print(completion.model)       # provider/model that answered
print(completion.provider)
print(completion.usage)       # Usage(prompt_tokens=..., completion_tokens=..., total_tokens=...)
print(completion.latency)
print(completion.attempts)

# Streaming returns ChatStream / chunks with .choices[].delta.content
for chunk in llm.chat.completions.create(
    model="fast",
    messages=[{"role": "user", "content": "Count to 3"}],
    stream=True,
):
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="")
```

### 3) Catalog & health helpers

```python
llmf.models()                 # callable → list models (same as .list())
llmf.models.list(live=False)
llmf.models.resolve("fast")   # expand alias → concrete targets
llmf.models.check()           # real one-shot call per model; caches ~24h

llmf.providers()              # or .list()
llmf.health()                 # or .check() — quick ping

llmf.configure(timeout=30, routing="adaptive", race=2, exclude=["blockrun"])
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
llmf.discover()               # opt-in external keyless catalog
```

Env (optional): `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_MODEL`, `LLMF_ROUTING`.

**Proxy:** HTTP(S) or SOCKS (`socks5://`, `socks5h://`, `socks4://`, …) via `proxy=` / `--proxy` / `LLMF_PROXY`.

---

## CLI — full command reference

```text
usage: llmf [options] "question"              ask once (also reads stdin)
       llmf chat                              interactive chat (/reset, /exit)
       llmf models [list|check|resolve NAME]  catalog / live probe / expand alias
       llmf doctor [--all]                    alias of `models check`
       llmf providers | health                endpoints / quick ping
       llmf serve [--port N]                  local OpenAI-compatible server
       llmf version
```

### Commands

| Command | What it does |
|---------|----------------|
| `llmf "…"` / `llmf ask "…"` | One-shot question |
| `llmf chat` | Interactive REPL (`/reset`, `/exit`) |
| `llmf models` / `llmf models list` | Table of known models |
| `llmf models list --live` | Also query providers’ `/models` |
| `llmf models resolve fast` | Print what an alias expands to |
| `llmf models check` | Call every model once (health cache) |
| `llmf doctor` | Same as `models check` |
| `llmf doctor --all` | Include models discovered live |
| `llmf doctor --include-limited` | Also hit strict daily-quota providers |
| `llmf doctor --no-save` | Do not write the health cache |
| `llmf providers` | Provider table |
| `llmf health` | Quick OK/FAIL ping per default target |
| `llmf serve` | Local OpenAI-compatible HTTP server |
| `llmf version` | Print version |

### Global flags

| Flag | Meaning |
|------|---------|
| `-m` / `--model` | Alias, fuzzy name, or `provider/model` |
| `-p` / `--provider` | Force provider (see `llmf providers`) |
| `-s` / `--system` | System prompt |
| `-i` / `--interactive` | REPL |
| `--image PATH` | Image path/URL (repeatable) |
| `--max-tokens N` | Max new tokens |
| `-t` / `--temperature` | Sampling temperature |
| `--stream` | Stream tokens to stdout |
| `--json` | Machine-readable result |
| `--routing ranked\|adaptive` | Fallback strategy |
| `--race N` | Hedge: try N providers in parallel |
| `--timeout SEC` | Per-request timeout |
| `--proxy URL` | `http://` / `https://` / `socks5://` / `socks5h://` / `socks4://` |
| `-v` / `--verbose` | Show which provider/model answered |
| `-V` / `--version` | Version (argparse) |
| `--live` | For `models list`: live catalog |
| `--all` | For `doctor`: include live model ids |
| `--include-limited` | For `doctor`: quota-limited providers |
| `--no-save` | For `doctor`: skip cache write |
| `--host` `--port` | For `serve` (default `127.0.0.1:8000`) |
| `--api-key` | For `serve`: require Bearer token |
| `--cors` | For `serve`: allow browser CORS |
| `--strict-models` | For `serve`: 404 unknown model names |
| `--no-fallback` | For `serve`: do not switch model on failure |

### Terminal examples

**One-shot ask**

```text
$ llmf "Say hi in one short sentence."
Hello! How can I help you today?

$ llmf -v "2+2=?"
ovh/Meta-Llama-3.3-70B-Instruct
4
```

**JSON output**

```text
$ llmf --json "Say hi in one short sentence."
{"text": "Hello! How can I help you today?", "provider": "…", "model": "…", "reasoning": null, "usage": {…}, "latency": 0.41}
```

**Models / providers / health**

```text
$ llmf models
MODEL                                          TAGS              STATUS
ovh/Meta-Llama-3.3-70B-Instruct                best,code
chatjimmy/…                                    fast
…

$ llmf models resolve fast
chatjimmy/…

$ llmf providers
PROVIDER         DEFAULT MODEL              MIN GAP  NOTE
ovh              Meta-Llama-3.3-70B-Instruct
…

$ llmf health
OK    ovh              Meta-Llama-3.3-70B-Instruct   0.85s
FAIL  blockrun         …                            12.01s  timeout
```

**Doctor**

```text
$ llmf doctor
Testing every model once (providers in parallel)...
OK    ovh/Meta-Llama-3.3-70B-Instruct                 0.90s  Hello…
FAIL  some-provider/some-model                        5.00s  HTTP 429
…
```

**Local server**

```text
$ llmf serve --port 8000
# listens on http://127.0.0.1:8000  (OpenAI-compatible /v1/chat/completions, /v1/models, …)
```

---

## Behaviour notes

- Fallback order prefers faster/cleaner targets; failures get a **cooldown** (longer on HTTP 429).
- `routing="adaptive"` uses latency EWMA; `race=N` sends parallel hedged requests.
- `doctor` / `models.check()` results are **cached ~24 hours** to demote dead models.
- Empty “HTTP 200” bodies and pure-reasoning empty content are treated as failures.
- If every target fails → `llmf.AllProvidersFailed` with `.errors`.

Public free endpoints change often — re-check with `llmf health` and `llmf doctor`.

---

## Safety

- Endpoints are **unofficial and free**. They may rate-limit, change, or disappear.
- **Do not send secrets**, passwords, or personal data.
- `discover()` contacts external catalogs (opt-in).
- Default `llmf serve` binds **localhost** and disables CORS unless you pass `--cors` / `--api-key`.

---

## Development

```bash
git clone https://github.com/MoonLite-Br/llmfree.git
cd llmfree
python -m unittest discover -s tests -v
python -m build && twine check dist/*
```

See [CHANGELOG.md](CHANGELOG.md) for 0.1 → 0.3 history.

---

## License

MIT © 2026 Html / [MoonLite-Br](https://github.com/MoonLite-Br/llmfree)
