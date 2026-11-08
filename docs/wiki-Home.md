# llmf (llmfree) Wiki

**Free, keyless LLMs behind one call** — with automatic fallback, a vetted catalogue, and an OpenAI-compatible server.

| | |
|--|--|
| **PyPI** | [llmf](https://pypi.org/project/llmf/) |
| **Repo** | [MoonLite-Br/llmfree](https://github.com/MoonLite-Br/llmfree) |
| **Install** | `pip install -U llmf` |
| **License** | MIT |

## Pages

- [[Security]] — threat model, `--public` / `--cloudflare`, what we do and do not claim
- [[Malware-and-false-positives]] — why scanners may flag free-LLM clients, and how we ship
- [[Quick-start]] — install, first call, CLI, serve
- [[Providers]] — catalogue, opt-in providers, doctor
- [[FAQ]] — common questions

## Quick example

```bash
pip install -U llmf
python -c "import llmf; print(llmf.chat('What is the capital of Vietnam?'))"
llmf doctor
llmf serve   # OpenAI-compatible on http://127.0.0.1:8000/v1
```

> Public free endpoints change, throttle, or disappear. Do not send secrets. Run `llmf doctor` regularly. llmf is not affiliated with any upstream provider.
