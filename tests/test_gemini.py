"""Gemini REST istemcisi testleri (sahte HTTP oturumu)."""

import json

import fiyat_kontrol as fk
import pytest


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok(result):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]})


def err(status, message):
    return FakeResponse(status, {"error": {"code": status, "message": message}})


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


RESULT = {"planlar": [{"plan_id": "a/b"}]}


def client(responses, models=("m1", "m2")):
    sleeps = []
    session = FakeSession(responses)
    c = fk.GeminiClient("gizli-anahtar", models, session, sleep=sleeps.append, retry_wait=1)
    return c, session, sleeps


def test_success_uses_header_key_and_json_schema():
    c, session, _ = client([ok(RESULT)])
    assert c.generate_json("istem", fk.RESPONSE_SCHEMA) == RESULT
    assert c.model == "m1"
    req = session.requests[0]
    assert req["url"].endswith("/models/m1:generateContent")
    assert "gizli-anahtar" not in req["url"]
    assert req["headers"]["x-goog-api-key"] == "gizli-anahtar"
    cfg = req["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == fk.RESPONSE_SCHEMA
    assert "tools" not in req["json"]  # Google Search grounding yok


def test_missing_model_falls_through_to_next_and_is_remembered():
    c, session, _ = client([err(404, "models/m1 is not found"), ok(RESULT), ok(RESULT)])
    c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert c.model == "m2"
    c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert session.requests[-1]["url"].endswith("/models/m2:generateContent")


def test_rate_limit_retries_once_then_succeeds():
    c, _, sleeps = client([err(429, "quota"), ok(RESULT)])
    assert c.generate_json("istem", fk.RESPONSE_SCHEMA) == RESULT
    assert sleeps == [1]


def test_rate_limit_twice_raises_unavailable():
    c, _, _ = client([err(429, "quota"), err(429, "quota")])
    with pytest.raises(fk.GeminiUnavailable) as exc:
        c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert "429" in str(exc.value) and "gizli-anahtar" not in str(exc.value)


def test_all_models_missing_raises():
    c, _, _ = client([err(404, "not found"), err(400, "model m2 is not supported")])
    with pytest.raises(fk.GeminiUnavailable, match="çalışan model bulunamadı"):
        c.generate_json("istem", fk.RESPONSE_SCHEMA)


def test_falls_back_to_response_schema_field():
    c, session, _ = client(
        [err(400, 'Invalid JSON payload received. Unknown name "responseJsonSchema"'), ok(RESULT)]
    )
    assert c.generate_json("istem", fk.RESPONSE_SCHEMA) == RESULT
    cfg = session.requests[-1]["json"]["generationConfig"]
    assert "responseJsonSchema" not in cfg
    price = cfg["responseSchema"]["properties"]["planlar"]["items"]["properties"]["yeni_fiyat_tl"]
    assert price == {"type": "NUMBER", "nullable": True}


def test_non_json_answer_raises():
    bad = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "merhaba"}]}}]})
    c, _, _ = client([bad])
    with pytest.raises(fk.GeminiUnavailable):
        c.generate_json("istem", fk.RESPONSE_SCHEMA)


def test_fenced_json_is_accepted():
    fenced = FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"text": "```json\n" + json.dumps(RESULT) + "\n```"}]}}]}
    )
    c, _, _ = client([fenced])
    assert c.generate_json("istem", fk.RESPONSE_SCHEMA) == RESULT


def test_prompt_contains_rules_and_targets():
    t = fk.collect_targets(
        {
            "servisler": [],
            "operator_paketleri": [
                {
                    "id": "turkcell-x",
                    "operator": "Turkcell",
                    "ad": "Turkcell X",
                    "fiyat_tl": 500,
                    "periyot": "aylik",
                    "icerir": [],
                    "kaynak": "https://x",
                    "kontrol_tarihi": "2026-11-01",
                    "dogrulandi": True,
                    "izleme_url": "https://x",
                    "kaynak_notu": "12 ay taahhütlü",
                }
            ],
        }
    )
    prompt = fk.build_prompt("https://x", t, "METİN 500TL")
    assert "paket/turkcell-x" in prompt and "500 TL" in prompt
    assert "taahhüt" in prompt and "kampanya" in prompt.lower()
    assert "en fazla 20 kelimelik" in prompt
    assert "METİN 500TL" in prompt


def test_requests_are_paced():
    sleeps = []
    clock = iter([0.0, 2.0, 2.0]).__next__  # 1. istek t=0, 2. istek t=2 → 4 sn bekle
    session = FakeSession([ok(RESULT), ok(RESULT)])
    c = fk.GeminiClient("k", ["m1"], session, sleep=sleeps.append, min_interval=6.0, clock=clock)
    c.generate_json("a", fk.RESPONSE_SCHEMA)
    c.generate_json("b", fk.RESPONSE_SCHEMA)
    assert sleeps == [4.0]
