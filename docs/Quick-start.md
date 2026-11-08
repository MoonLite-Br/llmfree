# Quick start

```bash
pip install -U llmf
# optional browser-like TLS:
pip install -U "llmf[stealth]"
```

## Python

```python
import llmf
print(llmf.chat("What is the capital of Vietnam?"))

from llmf import LLMF
llm = LLMF()
r = llm.chat.completions.create(
    model="best",
    messages=[{"role": "user", "content": "Hello"}],
)
print(r.choices[0].message.content, r.model)
```

## CLI

```bash
llmf "Explain the GIL"
llmf doctor
llmf models
llmf serve          # http://127.0.0.1:8000/v1
```

## OpenAI SDK against local serve

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="x")
c.chat.completions.create(model="best", messages=[{"role": "user", "content": "hi"}])
```

More: [README](https://github.com/MoonLite-Br/llmfree/blob/main/README.md) · [[Providers]] · [[Security]]
