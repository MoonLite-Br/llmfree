"""Turn friendly inputs (str / messages / images) into OpenAI-style messages."""

from __future__ import annotations

import base64
import copy
import mimetypes
import os
from typing import Any, List, Optional, Sequence, Union

Prompt = Union[str, Sequence[dict]]


def _sniff(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def image_url(img: Any) -> str:
    """URL / data-URI / local path / raw bytes -> something an API accepts."""
    if isinstance(img, (bytes, bytearray)):
        data = bytes(img)
        return "data:%s;base64,%s" % (_sniff(data), base64.b64encode(data).decode())
    s = str(img)
    if s.startswith(("http://", "https://", "data:")):
        return s
    if os.path.isfile(s):
        with open(s, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(s)[0] or _sniff(data)
        return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())
    raise FileNotFoundError("image not found: %r" % s)


def build_messages(prompt: Prompt, system: Optional[str] = None,
                   images: Optional[Sequence[Any]] = None) -> List[dict]:
    if isinstance(prompt, str):
        msgs: List[dict] = [{"role": "user", "content": prompt}]
    else:
        msgs = copy.deepcopy([dict(m) for m in prompt])
        if not msgs:
            raise ValueError("messages must not be empty")
    if images:
        idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
        if idx is None:
            raise ValueError("images need a user message to attach to")
        content = msgs[idx].get("content", "")
        parts = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
        parts += [{"type": "image_url", "image_url": {"url": image_url(i)}} for i in images]
        msgs[idx]["content"] = parts
    if system and not (msgs and msgs[0].get("role") == "system"):
        msgs.insert(0, {"role": "system", "content": system})
    return msgs
