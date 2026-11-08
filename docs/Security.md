# Security

This page summarizes the security model of **llmf**. Full detail lives in the [README “Security model”](https://github.com/MoonLite-Br/llmfree/blob/main/README.md) section.

## What llmf is

- A **stdlib-only** Python client and optional local server for *public, unofficial, free* LLM endpoints.
- No account with those providers is required for the default path; prompts go to third parties you do not control.
- Optional internet-facing mode (`llmf serve --public` / `--cloudflare`) adds auth, rate limits, and anti-bot checks.

## Design goals

| Area | Behaviour |
|------|-----------|
| Dependencies | Zero required runtime deps; optional `curl_cffi` only for TLS fingerprinting |
| Secrets | API keys (when you set them for `--public`) are compared in constant time, never logged in full |
| Local default | `llmf serve` binds loopback, no auth required — intended for the same machine |
| Public mode | Requires a bearer key (generated if omitted), rate limits, body/token caps, optional IP allow/deny |
| Anti-bot | Proof-of-work (default) or Cloudflare Turnstile for browser sessions; sessions are IP-bound and short-lived |
| Proxy trust | `X-Forwarded-For` / `CF-Connecting-IP` accepted **only** from a loopback peer when `--trust-proxy` is set |
| Upstream I/O | Only `http(s)` URLs; response size and stream limits; control characters stripped from upstream error text |

## What we do **not** claim

- Not a WAF or DDoS shield — put Cloudflare (or similar) in front for volumetric attacks.
- Quick Cloudflare tunnels get a new random hostname each run.
- Free upstream quotas still limit total throughput.
- Proof-of-work raises the cost of scripted abuse; it does not make abuse impossible.
- Web sessions cannot send images/tools and are stricter than API keys by design.

## Reporting issues

Please open a [GitHub issue](https://github.com/MoonLite-Br/llmfree/issues) for security-relevant bugs. Prefer minimal public detail until a fix is ready; we do not currently run a separate paid bug bounty.

## Related

- [[Malware-and-false-positives]]
- [SECURITY settings on the repo](https://github.com/MoonLite-Br/llmfree/security) (Dependabot / secret scanning as enabled by the owner)
