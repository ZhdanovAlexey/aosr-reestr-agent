"""Единственное место, где вызываются модели. Сюда же позже встанет анонимизация."""
from __future__ import annotations

import base64
import http.client
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .errors import AosrError

# Любой сервис с OpenAI-совместимым /chat/completions и моделями со зрением; по умолчанию — хаб neuraldeep.
BASE_URL = os.environ.get("AOSR_LLM_BASE_URL", "https://api.neuraldeep.ru/v1").rstrip("/")
DEFAULT_KEY_CMD = "~/.local/bin/neuraldeep-hub-key"


def api_key() -> str:
    key = os.environ.get("NEURALDEEP_API_KEY", "").strip()
    if key:
        return key
    cmd = str(Path(os.environ.get("NEURALDEEP_KEY_CMD", DEFAULT_KEY_CMD)).expanduser())
    try:
        key = subprocess.run([cmd], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        key = ""
    if not key:
        raise AosrError("model_error", "нет ключа хаба: задайте NEURALDEEP_API_KEY или NEURALDEEP_KEY_CMD")
    return key


def _post(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _extract_object(content) -> dict:
    text = str(content or "")
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b <= a:
        raise ValueError("в ответе нет JSON-объекта")
    obj = json.loads(text[a:b + 1])
    if not isinstance(obj, dict):
        raise ValueError("ответ не JSON-объект")
    return obj


def chat_json(model: str, prompt: str, images: list[bytes], *, transport=None, timeout: int = 240) -> dict:
    """Спросить модель и вернуть JSON-объект из её ответа."""
    transport = transport or _post
    key = api_key()
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(i).decode()}}
                for i in images]
    body = {"model": model, "temperature": 0, "max_tokens": 4000, "messages": [{"role": "user", "content": content}]}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last = ""
    for _ in range(2):
        try:
            data = transport(f"{BASE_URL}/chat/completions", headers, body, timeout)
        except urllib.error.HTTPError as e:
            last = f"хаб ответил {e.code}"
            if e.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as e:
            last = f"сеть или ответ не JSON: {type(e).__name__}"
            continue
        try:
            return _extract_object(data["choices"][0]["message"].get("content"))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            raise AosrError("model_error", f"модель {model} вернула не JSON-объект ({e})") from None
    raise AosrError("model_error", f"модель {model} недоступна: {last}".replace(key, "***"))
