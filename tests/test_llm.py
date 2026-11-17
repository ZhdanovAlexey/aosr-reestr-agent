import urllib.error

import pytest

from aosr import llm
from aosr.errors import AosrError
from aosr.llm import chat_json


def reply(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("NEURALDEEP_API_KEY", "sk-secret-123")


def test_fenced_json_is_parsed_and_request_is_shaped():
    seen = {}
    def transport(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return reply('```json\n{"номер_акта": "ЗР/ВГ/1"}\n```')
    assert chat_json("m1", "перепиши", [b"\xff\xd8a", b"\xff\xd8b"], transport=transport) == {"номер_акта": "ЗР/ВГ/1"}
    body = seen["body"]
    assert seen["url"] == "https://api.neuraldeep.ru/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-secret-123"
    assert (body["model"], body["temperature"]) == ("m1", 0)
    parts = body["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_plain_json_with_text_around():
    assert chat_json("m", "p", [], transport=lambda *a: reply('Вот ответ: {"a": 1} Готово.')) == {"a": 1}


@pytest.mark.parametrize("content", ["Извините, не могу", "", "[1, 2]", None])
def test_not_a_json_object_is_model_error(content):
    with pytest.raises(AosrError) as e:
        chat_json("m", "p", [], transport=lambda *a: reply(content))
    assert e.value.code == "model_error"


def test_one_retry_on_network_error():
    calls = []
    def transport(*a):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("timed out")
        return reply('{"ok": true}')
    assert chat_json("m", "p", [], transport=transport) == {"ok": True} and len(calls) == 2


def test_gives_up_after_second_failure_without_leaking_key():
    def transport(url, headers, body, timeout):
        raise urllib.error.HTTPError(url, 401, f"bad key {headers['Authorization']}", {}, None)
    with pytest.raises(AosrError) as e:
        chat_json("m", "p", [], transport=transport)
    assert e.value.code == "model_error" and "sk-secret-123" not in e.value.message


def test_key_from_command(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALDEEP_API_KEY")
    script = tmp_path / "key.sh"
    script.write_text("#!/bin/sh\necho sk-from-cmd\n")
    script.chmod(0o755)
    monkeypatch.setenv("NEURALDEEP_KEY_CMD", str(script))
    assert llm.api_key() == "sk-from-cmd"


def test_no_key_is_model_error(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALDEEP_API_KEY")
    monkeypatch.setenv("NEURALDEEP_KEY_CMD", str(tmp_path / "missing"))
    with pytest.raises(AosrError) as e:
        llm.api_key()
    assert e.value.code == "model_error"
