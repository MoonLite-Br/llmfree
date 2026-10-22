# llmf (llmfree)

**Một cú gọi duy nhất cho các LLM miễn phí, không cần API key.**
Không đăng ký, không khai báo nhà cung cấp, không phụ thuộc thư viện ngoài (chỉ Python stdlib, chạy tốt trên Termux).

```python
import llmf

print(llmf.chat("Xin chào, bạn là ai?"))
```

Chỉ vậy thôi. `llmf` tự chọn endpoint đang sống, tự chuyển sang nhà cung cấp khác khi lỗi, và luôn trả về cùng một kiểu dữ liệu.

## Cài đặt

```bash
pip install llmf
```

Yêu cầu Python ≥ 3.8. Không có dependency.

## Cú pháp thống nhất

Mọi nhà cung cấp, mọi model đều dùng **cùng một hàm, cùng tham số**:

```python
llmf.chat("câu hỏi")                                   # tự động chọn + fallback
llmf.chat("câu hỏi", model="best")                     # theo mục đích: fast | best | code | vision | reasoning
llmf.chat("câu hỏi", model="llama")                    # gõ tên gần đúng, không phân biệt hoa/thường
llmf.chat("câu hỏi", model="ovh/Qwen3.5-397B-A17B")    # chỉ định đích danh: nhà_cung_cấp/model
llmf.chat("câu hỏi", model=["best", "fast"])           # thử lần lượt

llmf.chat("...", system="Trả lời ngắn gọn", max_tokens=300, temperature=0.3)
llmf.chat("Mô tả ảnh này", images=["anh.jpg"])         # ảnh: đường dẫn / URL / bytes
llmf.chat("Trả JSON", json=True)
llmf.chat([{"role": "user", "content": "hi"}])         # hoặc danh sách messages kiểu OpenAI
```

Kết quả là `Reply` – **một `str`** kèm metadata:

```python
r = llmf.chat("2+2=?")
print(r)             # "4"  (đã strip, đã bỏ phần reasoning)
r.provider, r.model  # ai đã trả lời
r.reasoning          # chain-of-thought nếu có (không lẫn vào câu trả lời)
r.usage, r.latency, r.attempts
```

### Streaming, hội thoại, async

```python
for piece in llmf.stream("Đếm từ 1 đến 10"):
    print(piece, end="", flush=True)

s = llmf.session(system="Bạn là trợ lý ngắn gọn")   # nhớ lịch sử
s("Tên tôi là An")
print(s("Tên tôi là gì?"))

reply = await llmf.achat("hi")                       # async
async for piece in llmf.astream("hi"): ...
```

Streaming chỉ fallback **trước khi** có chunk đầu tiên; sau đó lỗi sẽ được raise.

## Dòng lệnh

```bash
llmf "Giải thích GIL trong Python"
cat code.py | llmf "Review đoạn code này" -m code
llmf -i                      # chat tương tác (/reset, /exit)
llmf --stream "kể chuyện cười"
llmf models                  # danh sách model (--live: hỏi trực tiếp từng nhà cung cấp)
llmf providers
llmf health                  # kiểm tra endpoint nào đang sống
python -m llmf "hi"
```

## Nó hoạt động thế nào

- **Chuỗi fallback** theo thứ tự nhanh/sạch nhất: `ovh → kilo-openrouter → chatjimmy → kilo-gateway → pollinations → llm7 → blockrun → freeai`.
- Endpoint vừa lỗi bị **hạ ưu tiên (cooldown)** một lúc; lỗi 429 thì 60 giây.
- Pollinations bị giới hạn 1 request/15s nên tự được **giãn nhịp** và xếp cuối.
- **Làm sạch đầu ra**: bỏ `reasoning`, tách `<think>…</think>`, strip `\n\n`, bóc khối `<|stats|>` của ChatJimmy, coi câu trả lời rỗng / lỗi giấu trong HTTP 200 là thất bại để chuyển nhà khác.
- `max_tokens` mặc định 1024 (model reasoning cần ≥ 200, nếu không `content` sẽ rỗng).
- Không retry vô ích: lỗi tạm thời (mạng, 5xx, timeout) thử lại 1 vòng; 4xx / 429 thì bỏ qua đích đó.

Khi tất cả đều thất bại sẽ có `llmf.AllProvidersFailed` với danh sách `.errors` chi tiết từng nơi.

## Tuỳ biến (không bắt buộc)

```python
llmf.configure(timeout=30, exclude=["blockrun"])      # hoặc only=["ovh", "llm7"]

# Thêm endpoint OpenAI-compatible của riêng bạn
llmf.register("lab", "http://localhost:11434/v1", ["llama3"], front=True)

# Endpoint hardcode bị chết? Lấy danh sách còn sống từ stillworks (opt-in)
llmf.discover()

c = llmf.Client(timeout=20)       # client độc lập, không dùng chung trạng thái
```

Biến môi trường: `LLMF_MODEL`, `LLMF_TIMEOUT`. Debug: `logging.getLogger("llmf").setLevel("DEBUG")`.

## Lưu ý quan trọng

- Đây là các endpoint **công khai, miễn phí, không chính thức**. Chúng có thể đổi, chậm, giới hạn hoặc biến mất bất cứ lúc nào – danh sách trong gói được xác minh ngày 2026-10-22. Hãy dùng `llmf health` và `llmf.discover()`.
- **Đừng gửi dữ liệu nhạy cảm** (mật khẩu, khoá, dữ liệu cá nhân): prompt đi tới máy chủ bên thứ ba ẩn danh, và `discover()` còn dùng endpoint của người lạ.
- Tôn trọng ToS và rate limit của từng dịch vụ; không spam. Dùng thương mại cần đọc điều khoản.
- `llmf` không liên kết với bất kỳ nhà cung cấp nào.
- Streaming trên phần lớn nhà cung cấp chưa được kiểm chứng trên endpoint thật (nếu họ không hỗ trợ, llmf nhận cả câu trả lời rồi trả một lần).

## Phát triển

```bash
git clone https://github.com/MoonLite-Br/llmfree && cd llmf
python -m unittest discover -s tests -v      # test chạy offline với server giả lập
```

Cấu trúc:

```
src/llmf/
  client.py        Client, Session, Stream: fallback, cooldown, rate-limit
  registry.py      danh mục provider + phân giải tên model (alias/fuzzy)
  providers/       builtin.py (catalogue), openai_compat.py, chatjimmy.py
  _messages.py     str/messages/ảnh -> messages chuẩn
  _think.py        tách <think> (hỗ trợ streaming)
  cli.py           lệnh `llmf`
```

Thêm nhà cung cấp mới tương thích OpenAI chỉ cần thêm một `ProviderSpec` vào `providers/builtin.py`.

## License

MIT
