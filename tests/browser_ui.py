"""Manual browser test (needs Playwright + Chromium): python tests/browser_ui.py"""
import hashlib, os, sys, threading
os.environ["LLMF_NO_CACHE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
import test_server as ts
from playwright.sync_api import sync_playwright

srv, base = ts.start(public=True, ui=True, pow_bits=12, session_rate=120)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(base + "/")
    # sha256 + zeroBits parity with hashlib
    for s in ["", "abc", "v1.1.a.12.b:77", "x" * 55, "x" * 56, "x" * 64, "é" * 100]:
        got = pg.evaluate("s => Array.from(llmf._sha256(new TextEncoder().encode(s))).map(b=>b.toString(16).padStart(2,'0')).join('')", s)
        assert got == hashlib.sha256(s.encode()).hexdigest(), s
    assert pg.evaluate("llmf._zeroBits(new Uint8Array([0,0x1f,255]))") == 11
    pg.fill("#box", "xin chào <img src=x onerror=window.pwned=1>")
    pg.click("#send")
    pg.wait_for_selector(".m.assistant .t:not(:text('…'))", timeout=30000)
    txt = pg.inner_text(".m.assistant .t")
    print("assistant:", repr(txt))
    assert txt and txt != "…"
    assert pg.evaluate("window.pwned") is None and pg.locator("#log img").count() == 0
    assert pg.locator(".m.user .t").inner_text().startswith("xin chào <img")
    # persists
    pg.reload()
    assert pg.locator(".m").count() == 2
    pg.click("#clear")
    assert pg.locator(".m").count() == 0
    assert not errs, errs
    b.close()
print("browser UI OK")
