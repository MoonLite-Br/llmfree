/* llmf browser client: proof-of-work session + OpenAI-style chat helpers.
   Include with <script src="/_llmf/client.js"></script>, then:
     const text = await llmf.chat([{role:"user", content:"Xin chào"}]);
     await llmf.stream(messages, {onDelta: t => ..., signal});
     llmf.fetch("/v1/models")  // fetch() with the session token attached                          */
(function () {
  "use strict";
  var K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,
    0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
    0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
    0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,
    0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
  var W = new Uint32Array(64);
  function sha256(bytes) {            // bytes: Uint8Array -> Uint8Array(32)
    var h = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
    var n = bytes.length, total = ((n + 9 + 63) >> 6) << 6, buf = new Uint8Array(total);
    buf.set(bytes); buf[n] = 0x80;
    var bits = n * 8, dv = new DataView(buf.buffer);
    dv.setUint32(total - 8, Math.floor(bits / 4294967296)); dv.setUint32(total - 4, bits >>> 0);
    for (var o = 0; o < total; o += 64) {
      var i, a, b, c, d, e, f, g, hh, t1, t2, s0, s1;
      for (i = 0; i < 16; i++) W[i] = dv.getUint32(o + i * 4);
      for (i = 16; i < 64; i++) {
        s0 = ((W[i-15] >>> 7) | (W[i-15] << 25)) ^ ((W[i-15] >>> 18) | (W[i-15] << 14)) ^ (W[i-15] >>> 3);
        s1 = ((W[i-2] >>> 17) | (W[i-2] << 15)) ^ ((W[i-2] >>> 19) | (W[i-2] << 13)) ^ (W[i-2] >>> 10);
        W[i] = (W[i-16] + s0 + W[i-7] + s1) | 0;
      }
      a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; hh = h[7];
      for (i = 0; i < 64; i++) {
        s1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        t1 = (hh + s1 + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
        s0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        t2 = (s0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    var out = new Uint8Array(32), ov = new DataView(out.buffer);
    for (var j = 0; j < 8; j++) ov.setUint32(j * 4, h[j]);
    return out;
  }
  function zeroBits(d) {
    var n = 0;
    for (var i = 0; i < d.length; i++) {
      if (d[i] === 0) { n += 8; continue; }
      return n + Math.clz32(d[i]) - 24;
    }
    return n;
  }
  var enc = new TextEncoder();
  function solve(challenge, bits, onProgress) {      // time-sliced: never freezes the page
    return new Promise(function (resolve) {
      var counter = 0;
      (function step() {
        var end = Date.now() + 25;
        while (Date.now() < end) {
          if (zeroBits(sha256(enc.encode(challenge + ":" + counter))) >= bits) return resolve(counter);
          counter++;
        }
        if (onProgress) onProgress(counter);
        setTimeout(step, 0);
      })();
    });
  }

  var session = null, pending = null;
  function jget(url) { return fetch(url, {cache: "no-store"}).then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error((j.error && j.error.message) || r.status); return j; }); }); }
  function newSession(onStatus) {
    return jget("/_llmf/config").then(function (cfg) {
      var body = {};
      var done = function () {
        return fetch("/_llmf/session", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
          .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error((j.error && j.error.message) || r.status); return j; }); })
          .then(function (j) { session = {token: j.token, exp: Date.now() + (j.expires_in - 30) * 1000}; return session; });
      };
      if (cfg.antibot === "pow") {
        if (onStatus) onStatus("pow");
        return jget("/_llmf/challenge").then(function (ch) {
          return solve(ch.challenge, ch.bits).then(function (c) { body = {challenge: ch.challenge, counter: c}; return done(); });
        });
      }
      if (cfg.antibot === "turnstile") {
        if (onStatus) onStatus("turnstile");
        return turnstile(cfg.turnstile_sitekey).then(function (t) { body = {turnstile: t}; return done(); });
      }
      return done();
    });
  }
  function turnstile(sitekey) {
    return new Promise(function (resolve, reject) {
      var box = document.createElement("div");
      box.style.cssText = "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.5);z-index:99999";
      var inner = document.createElement("div"); box.appendChild(inner); document.body.appendChild(box);
      function render() {
        window.turnstile.render(inner, {sitekey: sitekey, callback: function (t) { box.remove(); resolve(t); },
          "error-callback": function () { box.remove(); reject(new Error("turnstile failed")); }});
      }
      if (window.turnstile) return render();
      var s = document.createElement("script");
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      s.onload = render; s.onerror = function () { box.remove(); reject(new Error("cannot load turnstile")); };
      document.head.appendChild(s);
    });
  }
  function ensure(onStatus) {
    if (session && session.exp > Date.now()) return Promise.resolve(session);
    if (!pending) pending = newSession(onStatus).then(function (s) { pending = null; return s; }, function (e) { pending = null; throw e; });
    return pending;
  }
  function authFetch(url, init, onStatus) {
    return ensure(onStatus).then(function (s) {
      init = Object.assign({}, init || {});
      init.headers = Object.assign({}, init.headers || {}, {Authorization: "Bearer " + s.token});
      return fetch(url, init).then(function (r) {
        if (r.status === 401) { session = null; if (!init._retried) { init._retried = true; return authFetch(url, init, onStatus); } }
        return r;
      });
    });
  }
  function payload(messages, o) {
    var b = Object.assign({model: "auto", messages: messages}, o.body || {});
    return {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b), signal: o.signal};
  }
  function fail(r) { return r.json().catch(function () { return {}; }).then(function (j) { var e = new Error((j.error && j.error.message) || ("HTTP " + r.status)); e.status = r.status; e.retryAfter = r.headers.get("Retry-After"); throw e; }); }
  function chat(messages, o) {
    o = o || {};
    return authFetch("/v1/chat/completions", payload(messages, o), o.onStatus).then(function (r) {
      if (!r.ok) return fail(r);
      return r.json().then(function (j) { return j.choices[0].message.content || ""; });
    });
  }
  function stream(messages, o) {
    o = o || {}; o.body = Object.assign({stream: true}, o.body || {});
    return authFetch("/v1/chat/completions", payload(messages, o), o.onStatus).then(function (r) {
      if (!r.ok) return fail(r);
      var rd = r.body.getReader(), dec = new TextDecoder(), buf = "", full = "";
      function pump() {
        return rd.read().then(function (x) {
          if (x.done) return full;
          buf += dec.decode(x.value, {stream: true});
          var i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            var ev = buf.slice(0, i); buf = buf.slice(i + 2);
            ev.split("\n").forEach(function (line) {
              if (line.indexOf("data:") !== 0) return;
              var d = line.slice(5).trim();
              if (!d || d === "[DONE]") return;
              var j; try { j = JSON.parse(d); } catch (e) { return; }
              if (j.error) throw new Error(j.error.message || "upstream error");
              var t = j.choices && j.choices[0] && j.choices[0].delta && j.choices[0].delta.content;
              if (t) { full += t; if (o.onDelta) o.onDelta(t, full, j.model); }
            });
          }
          return pump();
        });
      }
      return pump();
    });
  }
  window.llmf = {chat: chat, stream: stream, fetch: authFetch, session: ensure, _sha256: sha256, _zeroBits: zeroBits};
})();
