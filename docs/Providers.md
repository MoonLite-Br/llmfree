# Providers

llmf ships a **vetted catalogue**: a model is listed for automatic use only after real-network runs meet the project’s success threshold. Anything else can still be called as `provider/model`.

## Trust but verify

```bash
llmf doctor              # catalogue
llmf doctor --all        # + live free ids each provider lists
llmf models              # alive / flaky / dead from your history
```

Results are stored under `~/.cache/llmf/` (health + survival history). Unreliable models are demoted automatically.

## Opt-in / limited providers

Some providers are **opt-in** (not in the default automatic chain) or tightly rate-limited. See the README provider table for current names (`nottrack`, `notrack-ai`, `apifreellm`, etc.) and pacing behaviour.

## Custom endpoint

```python
llm = LLMF()
llm.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)
```

## Related

- [[Quick-start]]
- [README – Providers](https://github.com/MoonLite-Br/llmfree/blob/main/README.md)
