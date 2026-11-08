# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.7.x   | Yes       |
| < 0.7   | Best effort only |

## Reporting a vulnerability

Please open a [GitHub issue](https://github.com/MoonLite-Br/llmfree/issues) labeled `security`, or use [private vulnerability reporting](https://github.com/MoonLite-Br/llmfree/security/advisories/new) if enabled.

Include:

- Affected version (`pip show llmf` / `llmf version`)
- Minimal reproduction
- Impact (auth bypass, SSRF, data leak, etc.)

We aim to acknowledge within a few days. Please avoid posting exploit details publicly until a fixed release is out.

## Scope notes

- **llmf** talks to third-party free LLM HTTP APIs. Treat upstreams as untrusted; do not send secrets in prompts.
- `llmf serve --public` / `--cloudflare` enables auth, rate limits, and anti-bot controls. Default `llmf serve` is **loopback-only** and is not hardened for the open internet.
- Optional dependency `curl_cffi` (`llmf[stealth]`) is for TLS fingerprinting only.

## Malware / AV false positives

Open-source client + local server; zero required dependencies; published via GitHub Actions Trusted Publishing to PyPI as [`llmf`](https://pypi.org/project/llmf/).

Heuristic scanners sometimes flag multi-endpoint HTTP clients, SOCKS support, or a local HTTP server. See the wiki page [Malware and false positives](https://github.com/MoonLite-Br/llmfree/wiki/Malware-and-false-positives) once the wiki is published, or `docs/Malware-and-false-positives.md` in this repository.

There is **no known malware** in releases built from this repository.
