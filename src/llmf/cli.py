"""Command line: ``llmf "your question"``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from typing import List, Optional

from . import __version__, default_client
from .errors import LLMFError

COMMANDS = ("ask", "chat", "models", "doctor", "providers", "health", "serve", "version")

HELP = """\
usage: llmf [options] "question"            ask once (also reads stdin)
       llmf chat                            interactive chat (/reset, /exit)
       llmf models [list|check|resolve NAME]  what exists / does it really work / what does NAME expand to
       llmf doctor [--all]                  call every model once and report (alias of `models check`)
       llmf providers | health              endpoints / quick ping
       llmf serve [--port N]                local OpenAI-compatible server
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmf", usage=HELP, add_help=True,
                                description="Free, keyless LLMs behind one command.")
    p.add_argument("words", nargs="*", help="question, or one of: " + ", ".join(COMMANDS))
    p.add_argument("-m", "--model", help="model, alias (fast/best/code/vision/reasoning) or provider/model")
    p.add_argument("-p", "--provider", help="provider name (see `llmf providers`); combine with -m")
    p.add_argument("-s", "--system", help="system prompt")
    p.add_argument("-i", "--interactive", action="store_true", help="interactive chat (REPL)")
    p.add_argument("--image", action="append", default=[], help="image path/URL (repeatable)")
    p.add_argument("--max-tokens", type=int)
    p.add_argument("-t", "--temperature", type=float)
    p.add_argument("--stream", action="store_true", help="print the answer as it arrives")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--live", action="store_true", help="models: also query providers live")
    p.add_argument("--all", action="store_true", help="doctor: also test models found live (/models)")
    p.add_argument("--include-limited", action="store_true",
                   help="doctor: also test strictly quota-limited providers (e.g. chatai)")
    p.add_argument("--include-non-chat", action="store_true",
                   help="models/doctor --live/--all: keep TTS, embedding, guard, image... ids too")
    p.add_argument("--no-save", action="store_true", help="doctor: do not write the health cache")
    p.add_argument("--routing", choices=("ranked", "adaptive"), help="fallback order strategy")
    p.add_argument("--race", type=int, help="send each request to N providers at once")
    p.add_argument("--timeout", type=float)
    p.add_argument("--proxy", help="proxy URL: http://, https://, socks5://, socks5h://, socks4://")
    p.add_argument("--host", default="127.0.0.1", help="serve: bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="serve: port (default 8000)")
    p.add_argument("--api-key", help="serve: require this bearer key")
    p.add_argument("--cors", action="store_true", help="serve: allow browser (CORS) access")
    p.add_argument("--strict-models", action="store_true", help="serve: 404 on unknown model names")
    p.add_argument("--no-fallback", action="store_true", help="serve: never switch model on failure")
    p.add_argument("-v", "--verbose", action="store_true", help="show provider/model used")
    p.add_argument("-V", "--version", action="version", version="llmf " + __version__)
    return p


def _read_stdin() -> str:
    return "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read().strip()


def _ask(a, prompt, history: Optional[List[dict]] = None) -> str:
    c = default_client()
    kw = dict(model=a.model, provider=a.provider, system=a.system, max_tokens=a.max_tokens,
              temperature=a.temperature, race=a.race)
    if a.race:
        kw["race"] = a.race
    if a.image:
        kw["images"] = a.image
    msgs = (history or []) + [{"role": "user", "content": prompt}]
    if a.stream and not a.json:
        st = c.stream(msgs, **kw)
        for piece in st:
            sys.stdout.write(piece)
            sys.stdout.flush()
        sys.stdout.write("\n")
        reply = st.reply
        text = reply.text if reply else st.text
        src = reply.source if reply else ""
    else:
        reply = c.chat(msgs, **kw)
        text, src = reply.text, reply.source
        if a.json:
            print(json.dumps({"text": text, "provider": reply.provider, "model": reply.model,
                              "reasoning": reply.reasoning, "usage": reply.usage,
                              "latency": round(reply.latency, 3)}, ensure_ascii=False))
        else:
            print(text)
    if a.verbose and src:
        print("[%s]" % src, file=sys.stderr)
    return text


def _repl(a) -> int:
    history: List[dict] = []
    print("llmf %s - /reset clears history, /exit quits" % __version__, file=sys.stderr)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/reset":
            history.clear()
            continue
        try:
            text = _ask(a, line, history)
        except LLMFError as e:
            print("error: %s" % e, file=sys.stderr)
            continue
        history += [{"role": "user", "content": line}, {"role": "assistant", "content": text}]


def _table(rows: List[List[str]], header: List[str]) -> None:
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    for r in [header] + rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip())


def _cmd_models(a, c, args: List[str]) -> int:
    sub = args[0] if args else "list"
    if sub == "list":
        rows = c.models.list(live=a.live, include_non_chat=a.include_non_chat)
        if a.json:
            print(json.dumps([{"name": m.name, "tags": list(m.tags), "vision": m.vision,
                               "verified": m.verified} for m in rows], indent=2))
            return 0
        _table([[m.name, ",".join(list(m.tags) + (["vision"] if m.vision and "vision" not in m.tags else [])),
                 "" if m.verified else "unverified"] for m in rows], ["MODEL", "TAGS", "STATUS"])
        return 0
    if sub == "check":
        return _cmd_doctor(a, c)
    if sub == "resolve" and len(args) > 1:
        names = args[1:]
        for t in c.models.resolve(names if len(names) > 1 else names[0]):
            print(t)
        return 0
    print("usage: llmf models [list | check | resolve NAME]", file=sys.stderr)
    return 2


def _cmd_doctor(a, c) -> int:
    lock = threading.Lock()
    n_ok = n_bad = 0

    def show(r) -> None:
        nonlocal n_ok, n_bad
        with lock:
            if r.ok:
                n_ok += 1
            else:
                n_bad += 1
            if not a.json:
                detail = r.answer if r.ok else r.error
                print("%-5s %-58s %6.2fs  %s" % ("OK" if r.ok else "FAIL", r.name, r.latency, detail or ""),
                      flush=True)

    if not a.json:
        print("Testing every model once (providers in parallel)...", file=sys.stderr)
    results = c.models.check(providers=[a.provider] if a.provider else None, include_live=a.all,
                             include_limited=a.include_limited, include_non_chat=a.include_non_chat,
                             timeout=a.timeout or 30.0, save=not a.no_save, on_result=show)
    if a.json:
        print(json.dumps([{"name": r.name, "ok": r.ok, "latency": round(r.latency, 3),
                           "answer": r.answer, "error": r.error} for r in results],
                         ensure_ascii=False, indent=2))
    else:
        where = ""
        if not a.no_save and c.use_cache and c._cache_path():
            where = "  (saved: %s)" % c._cache_path()
        print("\n%d ok, %d failed%s" % (n_ok, n_bad, where), file=sys.stderr)
    return 0 if n_ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    a = _parser().parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    c = default_client()
    try:
        if a.timeout:
            c.configure(timeout=a.timeout)
        if a.proxy:
            c.configure(proxy=a.proxy)
        if a.routing:
            c.configure(routing=a.routing)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    words = a.words
    cmd = words[0] if words and words[0] in COMMANDS and (words[0] in ("ask", "chat", "models") or len(words) == 1) else None
    try:
        if cmd == "version":
            print(__version__)
        elif cmd == "providers":
            rows = c.providers.list()
            if a.json:
                print(json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2))
            else:
                _table([[r.name, r.default_model, "%gs" % r.min_interval if r.min_interval else "", r.note]
                        for r in rows], ["PROVIDER", "DEFAULT MODEL", "MIN GAP", "NOTE"])
        elif cmd == "models":
            return _cmd_models(a, c, words[1:])
        elif cmd == "doctor":
            return _cmd_doctor(a, c)
        elif cmd == "serve":
            from .server import serve

            if a.model:
                c.configure(model=a.model if not a.provider else "%s/%s" % (a.provider, a.model))
            elif a.provider:
                c.configure(model=a.provider)
            serve(c, a.host, a.port, api_key=a.api_key, cors=a.cors,
                  strict_models=a.strict_models, fallback=not a.no_fallback)
        elif cmd == "health":
            bad = 0
            for h in c.health.check():
                bad += not h.ok
                print("%-5s %-16s %-42s %6.2fs  %s" % ("OK" if h.ok else "FAIL", h.provider,
                                                      h.model, h.latency, h.error or ""))
            return 1 if bad == len(c.providers.list()) else 0
        else:
            rest = words[1:] if cmd in ("ask", "chat") else words
            prompt = " ".join(rest).strip()
            if a.interactive or (cmd == "chat" and not prompt and sys.stdin is not None and sys.stdin.isatty()):
                return _repl(a)
            piped = _read_stdin()
            prompt = ("%s\n\n%s" % (prompt, piped)).strip() if piped else prompt
            if not prompt:
                print(HELP, file=sys.stderr)
                return 2
            _ask(a, prompt)
    except LLMFError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except BrokenPipeError:  # e.g. ``llmf ... | head``
        return 0
    return 0
