<div align="center">

# llmf (llmfree)

**LLM miễn phí, không cần API key, chỉ một lời gọi: có fallback, danh mục đã kiểm chứng và server chuẩn OpenAI.**

[![PyPI](https://img.shields.io/pypi/v/llmf?color=2ea44f)](https://pypi.org/project/llmf/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/llmf?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/llmf)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) · Tiếng Việt

</div>

```bash
pip install -U llmf                  # đủ mọi thứ: thư viện, CLI, server cục bộ + ra internet (chỉ stdlib)
pip install -U "llmf[stealth]"       # tuỳ chọn: + curl_cffi (dấu vân tay TLS giống trình duyệt)
```
Một gói duy nhất, không Flask. Nhớ đặt trong dấu nháy khi dùng Termux/zsh.
```python
import llmf
print(llmf.chat("Thủ đô của Việt Nam là gì?"))
```

Không tài khoản, không API key, không khai báo nhà cung cấp. **Chỉ dùng thư viện chuẩn** (0 phụ thuộc bắt buộc), Python 3.8+, chạy trên Linux, macOS, Windows và **Termux/Android**.

> **Lưu ý.** Đây là các endpoint công khai, không chính thức: có thể đổi, bị giới hạn hoặc biến mất bất cứ lúc nào, và prompt đi tới bên thứ ba ẩn danh. Đừng gửi dữ liệu nhạy cảm. Chạy `llmf doctor` định kỳ. llmf không liên kết với bất kỳ nhà cung cấp nào.

## Tính năng chính

- **Một lời gọi**, cú pháp khớp OpenAI (`choices`, `usage`, `stream`, `tools`, `response_format`).
- **Fallback tự động**: cooldown theo model/nhà, phát hiện câu trả lời rỗng/lỗi giấu trong HTTP 200, `AllProvidersFailed` kèm báo cáo từng lần thử.
- **Danh mục đã kiểm chứng**: chỉ giữ model trả lời ≥ 2 lần thật với tỉ lệ ≥ 75 %; model khác vẫn dùng được bằng `provider/model`.
- **Lịch sử sống/chết**: `llmf models` hiện `alive 7/7`, `flaky 2/3`, `dead 0/3`; model kém tự bị đẩy xuống cuối.
- **Định tuyến theo tải**: giới hạn đồng thời mỗi nhà, request dư tự chuyển sang nhà khác; `race=N` lấy câu trả lời nhanh nhất.
- **Proxy HTTP/HTTPS/SOCKS** (stdlib thuần, chỉ proxy của bạn) và **transport giống trình duyệt** tuỳ chọn: `pip install "llmf[stealth]"`.
- **`llmf serve`**: server chuẩn OpenAI; có thể mở ra internet an toàn, kèm web chat, Cloudflare tunnel, anti-bot.

## Dùng nhanh

```python
from llmf import LLMF
llm = LLMF()
r = llm.chat.completions.create(model="best", messages=[{"role": "user", "content": "Xin chào"}])
print(r.choices[0].message.content, r.model)     # r.model cho biết nhà/model thật đã trả lời
```
```python
llmf.chat("hi", provider="ovh", proxy="socks5h://127.0.0.1:1080")
for piece in llmf.stream("Đếm từ 1 đến 5"): print(piece, end="")
s = llmf.session(system="Ngắn gọn"); s("Tên tôi là An"); s("Tên tôi là gì?")
```
Chọn model: `fast | best | code | vision | reasoning`, `"ovh/Qwen3.5-397B-A17B"`, tên gần đúng `"qwen"`, hoặc danh sách `["best", "fast"]`.

Cấu hình: `LLMF(timeout=30, deadline=120, proxy=..., routing="adaptive", race=2, exclude=[...], transport="auto", max_inflight=6)`.
Biến môi trường: `LLMF_MODEL`, `LLMF_TIMEOUT`, `LLMF_PROXY`, `LLMF_ROUTING`, `LLMF_TRANSPORT`, `LLMF_CACHE_DIR`, `LLMF_NO_CACHE=1`.

## Dòng lệnh

```bash
llmf "Giải thích GIL"
cat code.py | llmf "Review đoạn này" -m code
llmf chat
llmf models | doctor | providers | health | serve | version
llmf doctor --all --include-non-chat --include-limited     # kiểm tra thật mọi thứ
```
Kết quả `doctor` lưu ở `~/.cache/llmf/`. `python live_test.py` chạy ~60 phép thử thật và ghi `llmf_live_report.json`.

## `llmf serve`

> Mọi cờ (`--public`, `--cloudflare`, `--ui`, `--html`, `--app`, anti-bot, TLS...) đều có sẵn sau `pip install llmf`, không cần cài thêm gói nào.

```bash
llmf serve                                                    # http://127.0.0.1:8000/v1, chỉ cục bộ
llmf serve --cloudflare --ui                                  # web chat công khai (cần `cloudflared`: Termux `pkg install cloudflared`)
llmf serve --app "node main.js" --app-port 3000 --cloudflare  # chạy dự án Node của bạn + AI
llmf serve --html /sdcard/download/index.html --ui --public   # chỉ phục vụ đúng 1 file html
llmf serve --public --api-keys-file keys.txt --tls-cert c.pem --tls-key k.pem --allow-ip 203.0.113.0/24
```

Endpoint: `POST /v1/chat/completions` (stream), `GET /v1/models`, `GET /health`. Model lạ như `gpt-4o` = "tự động".

| Cờ | Tác dụng |
|---|---|
| `--public` | Hồ sơ internet: bind `0.0.0.0`, **bắt buộc API key** (tự sinh và in ra nếu bạn không đặt), giới hạn tốc độ, cấm IP, giới hạn body/token, anti-bot |
| `--cloudflare`, `--tunnel-token T` | Tunnel qua `cloudflared` của bạn; ngầm bật `--public` + `--trust-proxy` |
| `--ui` | Trang chat dựng sẵn (stream, lưu lịch sử, hiển thị an toàn) |
| `--html PATH` / `--web PATH` | 1 file (chỉ file đó) hoặc thư mục tĩnh (chặn `..`, file ẩn, symlink) |
| `--app "CMD"`, `--app-port`, `--app-dir` | Chạy dự án của bạn (nhận `$PORT`, `$OPENAI_BASE_URL`, `$OPENAI_API_KEY`) và reverse-proxy |
| `--api-key` (lặp được), `--api-keys-file` | Khoá Bearer |
| `--rate`, `--ip-rate`, `--session-rate` | Số request/phút theo key / IP / khách web |
| `--allow-ip`, `--deny-ip` | Danh sách CIDR |
| `--trust-proxy` | Lấy IP thật từ `CF-Connecting-IP`/`X-Forwarded-For`, **chỉ khi kết nối đến từ loopback** |
| `--cors`, `--cors-origin` | Mọi origin hoặc danh sách cho phép |
| `--max-body`, `--max-tokens-cap`, `--max-concurrent` | Giới hạn kích thước / tải |
| `--tls-cert`, `--tls-key` | HTTPS (TLS ≥ 1.2) + HSTS |
| `--antibot pow\|turnstile\|off` | Kiểm tra khách web (mặc định `pow` khi public) |
| `--log-file`, `--csp` | Log JSON (không có prompt/key); header CSP |

Trong trang web của bạn:
```html
<script src="/_llmf/client.js"></script>
<script>await llmf.stream([{role:"user",content:"Xin chào"}], {onDelta: (t, full) => out.textContent = full});</script>
```
Script tự giải proof-of-work và giữ token phiên ngắn hạn: **API key không bao giờ xuống trình duyệt**.

### Bảo mật: làm gì và không làm gì

- Có: so khớp key thời gian hằng, key không vào log, cấm IP sau nhiều lần sai (15 phút), giới hạn theo key/IP/khách, trần số kết nối, timeout socket, giới hạn body/`max_tokens`, PoW ký HMAC dùng một lần gắn với IP (Turnstile xác thực phía server, lỗi thì chặn), header bảo mật + CSP, không chèn HTML, lỗi chung chung (không lộ traceback/phiên bản Python), gỡ thông tin đăng nhập llmf trước khi proxy sang `--app`, header proxy chỉ tin từ loopback.
- **Không có**: đây không phải WAF/chống DDoS (hãy đặt Cloudflare phía trước); URL quick tunnel đổi mỗi lần chạy; chưa proxy WebSocket tới `--app`; `--app` chạy đúng lệnh bạn đưa; PoW chỉ làm tăng chi phí lạm dụng chứ không ngăn tuyệt đối; thông lượng thật vẫn bị các endpoint miễn phí chặn.
- Phát hiện lỗ hổng? Hãy mở *private security advisory* trên GitHub thay vì issue công khai.

## Nhà cung cấp

Thứ tự fallback: `ch-at → rewind-ai → ovh → kilo-openrouter → freeai → chatjimmy → kilo-gateway → pollinations → llm7 → blockrun → chatai` (`nottrack`, `notrack-ai`, `apifreellm` chỉ khi chỉ định). Xem bảng chi tiết ở [README.md](README.md#providers) hoặc chạy `llmf providers` / `llmf models`.

## Phát triển

```bash
git clone https://github.com/MoonLite-Br/llmfree && cd llmfree
pip install -e .
```
Xem [CHANGELOG.md](CHANGELOG.md). MIT © 2026 Html / MoonLite-Br
