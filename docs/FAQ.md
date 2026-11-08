# FAQ

**Is it really free?**  
Default routing uses public free/keyless endpoints. They can change or disappear. Optional providers may need their own signup; llmf does not bill you.

**Do my prompts stay private?**  
No for upstream calls — prompts go to third-party endpoints. Do not send secrets. For local-only models, register your own OpenAI-compatible server (e.g. Ollama).

**Why does antivirus warn me?**  
See [[Malware-and-false-positives]].

**Termux / Android?**  
Supported. Stdlib-only install is the reliable path; `curl_cffi` wheels may be unavailable on some devices — llmf falls back to urllib.

**How do I expose a public URL?**  
`llmf serve --cloudflare --ui` (needs `cloudflared`) or `--public` with your own TLS and API keys. Read [[Security]] first.

**Where is the changelog?**  
In the [README Changelog section](https://github.com/MoonLite-Br/llmfree/blob/main/README.md) (also on the PyPI project page) and [CHANGELOG.md](https://github.com/MoonLite-Br/llmfree/blob/main/CHANGELOG.md).
