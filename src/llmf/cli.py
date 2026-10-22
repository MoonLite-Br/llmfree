"""Command line: ``llmf "your question"``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from . import __version__, default_client
from .errors import LLMFError

COMMANDS = ("chat", "models", "providers", "health", "version")

HELP = """\
usage: llmf [options] "question"          ask once (also reads stdin)
       llmf -i                            interactive chat
       llmf models | providers | health   inspect what is available
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmf", usage=HELP, add_help=True,
                                description="Free, keyless LLMs behind one command.")
    p.add_argument("words", nargs="*", help="question, or one of: " + ", ".join(COMMANDS))
    p.add_argument("-m", "--model", help="model, alias (fast/best/code/vision/reasoning) or provider/model")
    p.add_argument("-s", "--system", help="system prompt")
    p.add_argument("-i", "--interactive", action="store_true", help="interactive chat (REPL)")
    p.add_argument("--image", action="append", default=[], help="image path/URL (repeatable)")
    p.add_argument("--max-tokens", type=int)
    p.add_argument("-t", "--temperature", type=float)
    p.add_argument("--stream", action="store_true", help="print the answer as it arrives")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--live", action="store_true", help="models: also query providers live")
    p.add_argument("--timeout", type=float)
    p.add_argument("-v", "--verbose", action="store_true", help="show provider/model used")
    p.add_argument("-V", "--version", action="version", version="llmf " + __version__)
    return p


def _read_stdin() -> str:
    return "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read().strip()


def _ask(a, prompt, history: Optional[List[dict]] = None) -> str:
    c = default_client()
    kw = dict(model=a.model, system=a.system, max_tokens=a.max_tokens, temperature=a.temperature)
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


def main(argv: Optional[List[str]] = None) -> int:
    a = _parser().parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    c = default_client()
    if a.timeout:
        c.configure(timeout=a.timeout)
    cmd = a.words[0] if a.words and a.words[0] in COMMANDS and len(a.words) == 1 else None
    try:
        if cmd == "version":
            print(__version__)
        elif cmd == "providers":
            rows = c.providers()
            if a.json:
                print(json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2))
            for r in rows if not a.json else []:
                print("%-16s default=%-42s %s" % (r.name, r.default_model, r.note))
        elif cmd == "models":
            rows = c.models(live=a.live)
            if a.json:
                print(json.dumps([{"name": m.name, "tags": m.tags, "vision": m.vision,
                                   "verified": m.verified} for m in rows], indent=2))
            for m in rows if not a.json else []:
                tags = list(m.tags) + (["vision"] if m.vision and "vision" not in m.tags else [])
                flags = ",".join(tags + ([] if m.verified else ["unverified"]))
                print("%-60s %s" % (m.name, flags))
        elif cmd == "health":
            bad = 0
            for h in c.health():
                bad += not h.ok
                print("%-4s %-16s %-42s %5.1fs %s" % ("OK" if h.ok else "FAIL", h.provider,
                                                     h.model, h.latency, h.error or ""))
            return 1 if bad == len(c.providers()) else 0
        elif a.interactive:
            return _repl(a)
        else:
            prompt = " ".join(a.words[1:] if a.words[:1] == ["chat"] else a.words).strip()
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
