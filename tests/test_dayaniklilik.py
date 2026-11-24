"""Hata dayanıklılığı (KR-052): yedek model, anahtar/kota hatası ayrımı, issue'ların
kendiliğinden kapanması, 2 günlük PR hatırlatması. Sahte HTTP yanıtlarıyla."""

import datetime as dt
import json

import fiyat_kontrol as fk
import pytest
from helpers import (
    EXXEN_URL,
    SPOTIFY_URL,
    TURKCELL_URL,
    FakeGemini,
    FakeGitHub,
    answer,
    default_answers,
    make_root,
    pages,
    run,
)

PRIMARY = "birincil-model"
FALLBACK = "yedek-model"
LABELS = [{"name": fk.ISSUE_LABEL}]


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok(result):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]})


def err(status, message="", details=None):
    payload = {"error": {"code": status, "message": message}}
    if details:
        payload["error"]["details"] = details
    return FakeResponse(status, payload)


DAILY_QUOTA = err(
    429,
    "You exceeded your current quota.",
    [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}],
)


class RouterSession:
    """Model adına göre yanıt verir. `rules[model]`: FakeResponse ya da 'cevap'
    (istemdeki kaynağa göre default_answers yanıtı)."""

    def __init__(self, rules, answers=None):
        self.rules = rules
        self.answers = answers or default_answers()
        self.calls: list[str] = []

    def post(self, url, headers=None, json=None, timeout=None):
        model = url.split("/models/")[1].split(":")[0]
        self.calls.append(model)
        rule = self.rules[model]
        if rule == "cevap":
            prompt = json["contents"][0]["parts"][0]["text"]
            src = next(u for u in (SPOTIFY_URL, EXXEN_URL, TURKCELL_URL) if f"kaynak: {u}" in prompt)
            return ok({"planlar": self.answers.get(src, [])})
        return rule


def gemini(rules, answers=None, fallback=FALLBACK):
    session = RouterSession(rules, answers)
    client = fk.GeminiClient("gizli", [PRIMARY], session, sleep=lambda s: None, retry_wait=1, fallback_model=fallback)
    return client, session


RESULT = {"planlar": []}


# --- istemci: yedek model ve hata türleri ---


def test_503_then_fallback_model_answers():
    c, s = gemini({PRIMARY: err(503, "The model is overloaded"), FALLBACK: ok(RESULT)})
    assert c.generate_json("istem", fk.RESPONSE_SCHEMA) == RESULT
    assert s.calls == [PRIMARY, PRIMARY, FALLBACK]  # birincil bir kez yeniden denendi
    assert c.last_model == FALLBACK and c.fallback_answers == 1
    # sonraki çağrı yine önce birincil modeli dener (503 geçicidir)
    s.rules[PRIMARY] = ok(RESULT)
    c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert s.calls[-1] == PRIMARY and c.last_model == PRIMARY


def test_both_models_fail_is_transient():
    c, s = gemini({PRIMARY: err(503, "overloaded"), FALLBACK: err(500, "internal")})
    with pytest.raises(fk.GeminiUnavailable) as exc:
        c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert exc.value.kind == fk.KIND_TRANSIENT
    assert PRIMARY in str(exc.value) and FALLBACK in str(exc.value) and "gizli" not in str(exc.value)


@pytest.mark.parametrize(
    "resp",
    [err(401, "API keys are not supported"), err(403, "Permission denied"), err(400, "API key not valid.")],
)
def test_key_error_no_fallback_and_no_more_requests(resp):
    c, s = gemini({PRIMARY: resp, FALLBACK: ok(RESULT)})
    for _ in range(3):
        with pytest.raises(fk.GeminiUnavailable) as exc:
            c.generate_json("istem", fk.RESPONSE_SCHEMA)
        assert exc.value.kind == fk.KIND_KEY
    assert s.calls == [PRIMARY]  # yedek denenmedi, sonraki çağrılar istek atmadı


def test_daily_quota_skips_wait_and_exhausted_model():
    sleeps = []
    session = RouterSession({PRIMARY: DAILY_QUOTA, FALLBACK: ok(RESULT)})
    c = fk.GeminiClient("gizli", [PRIMARY], session, sleep=sleeps.append, retry_wait=20, fallback_model=FALLBACK)
    c.generate_json("istem", fk.RESPONSE_SCHEMA)
    c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert sleeps == []  # günlük kotada beklemek boşuna
    assert session.calls == [PRIMARY, FALLBACK, FALLBACK]  # kotası dolan birincil yeniden denenmez
    assert c.fallback_answers == 2


def test_quota_on_both_is_quota_kind():
    c, _ = gemini({PRIMARY: DAILY_QUOTA, FALLBACK: err(429, "Quota exceeded, limit: 0")})
    with pytest.raises(fk.GeminiUnavailable) as exc:
        c.generate_json("istem", fk.RESPONSE_SCHEMA)
    assert exc.value.kind == fk.KIND_QUOTA


def test_minute_rate_limit_is_transient():
    assert fk.classify_error(429, '{"message": "Resource exhausted. Please retry in 30s"}') == fk.KIND_TRANSIENT
    assert fk.classify_error(503, "overloaded") == fk.KIND_TRANSIENT
    assert fk.classify_error(400, "Invalid JSON payload") == fk.KIND_OTHER


def test_fallback_same_as_primary_is_ignored():
    c, _ = gemini({PRIMARY: ok(RESULT)}, fallback=PRIMARY)
    assert c.fallback_model is None


def test_production_fallback_model_is_set():
    assert fk.FALLBACK_MODEL and fk.FALLBACK_MODEL not in fk.DEFAULT_MODELS


# --- akış: yedek model, karma yolu, issue metinleri ---


def test_runner_fallback_model_answers_and_is_reported(tmp_path):
    root = make_root(tmp_path)
    hike = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }
    client, session = gemini({PRIMARY: err(503, "overloaded"), FALLBACK: "cevap"}, default_answers(**hike))
    summary, gh, _ = run(root, gemini=client, page_map=pages(b="129"), weekly=True)
    assert summary["yedek_model"] == FALLBACK
    assert set(summary["yedek_model_kaynaklari"]) == {SPOTIFY_URL, EXXEN_URL, TURKCELL_URL}
    assert all(k["model"] == FALLBACK for k in summary["kaynaklar"] if k["durum"] == "ok")
    pr = gh.created_prs[0]
    assert f"`{FALLBACK}` (yedek model)" in pr["body"]
    assert gh.created_issues == [] or all("Gemini" not in t for t, _ in gh.created_issues)
    heartbeat = json.loads((root / "durum" / "son-calisma.json").read_text(encoding="utf-8"))
    assert heartbeat["yedek_model"] == FALLBACK and heartbeat["yedek_model_yanit_veren_kaynak"] == 3
    assert f"yedek model: {FALLBACK}" in fk.render_summary(summary)


def test_runner_both_fail_falls_back_to_fingerprint(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    run(root, day="2026-11-15", gemini=FakeGemini(default_answers()), gh=gh)  # karma kaydedilir
    client, session = gemini({PRIMARY: err(503, "overloaded"), FALLBACK: err(503, "overloaded")})
    run(root, day="2026-11-16", gemini=client, page_map=pages(a="219"), gh=gh)
    titles = [t for t, _ in gh.created_issues]
    assert "Manuel kontrol: Spotify fiyat sayfası değişti" in titles
    assert "Otomasyon: Gemini erişilemedi" in titles
    body = dict(gh.created_issues)["Otomasyon: Gemini erişilemedi"]
    assert "birincil ve yedek model" in body and "yanlış fiyat gösterilmez" in body
    assert FALLBACK in session.calls


def test_runner_key_error_opens_guiding_issue(tmp_path):
    root = make_root(tmp_path)
    client, session = gemini({PRIMARY: err(401, "API keys are not supported by this API"), FALLBACK: "cevap"})
    summary, gh, _ = run(root, gemini=client)
    assert [t for t, _ in gh.created_issues] == ["Otomasyon: Gemini anahtarı çalışmıyor"]
    body = gh.created_issues[0][1]
    for text in ("K3", "aistudio.google.com", "Secrets and variables", "yanlış fiyat gösterilmez", "kendisi kapatır"):
        assert text in body
    assert "gizli" not in body and "API keys are not supported" not in body  # ayrıntı yalnız logda
    assert session.calls == [PRIMARY]  # tek istek; yedek ve diğer kaynaklar boşuna denenmedi


def test_local_key_error_points_to_env_var(tmp_path):
    root = make_root(tmp_path)
    client, _ = gemini({PRIMARY: err(403, "denied"), FALLBACK: "cevap"})
    _, gh, _ = run(root, gemini=client, mode=fk.MODE_LOCAL, local_urls={SPOTIFY_URL})
    title, body = gh.created_issues[0]
    assert title == "Otomasyon (yerel): Gemini anahtarı çalışmıyor"
    assert "setx GEMINI_API_KEY" in body


def test_missing_key_in_actions_opens_key_issue(tmp_path):
    root = make_root(tmp_path)
    _, gh, _ = run(root, gemini=None)
    title, body = gh.created_issues[0]
    assert title == "Otomasyon: Gemini anahtarı çalışmıyor" and "tanımlı değil" in body


def test_runner_quota_issue(tmp_path):
    root = make_root(tmp_path)
    client, _ = gemini({PRIMARY: DAILY_QUOTA, FALLBACK: DAILY_QUOTA})
    _, gh, _ = run(root, gemini=client)
    title, body = gh.created_issues[0]
    assert title == "Otomasyon: Gemini günlük kotası doldu" and "yanlış fiyat gösterilmez" in body


# --- kendiliğinden kapanma ---


def issue(number, title, labels=LABELS):
    return {"number": number, "title": title, "body": "", "labels": labels}


def test_gemini_issues_close_when_gemini_answers(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(
        issues=[
            issue(7, "Otomasyon: Gemini erişilemedi"),
            issue(5, "Otomasyon (yerel): Gemini erişilemedi"),  # başka modun sorunu
            issue(11, "Otomasyon: Gemini anahtarı çalışmıyor"),
            issue(12, "Otomasyon: Gemini günlük kotası doldu", labels=[]),  # bot etiketi yok
            issue(8, "Manuel kontrol: Spotify fiyat sayfası değişti"),  # insan bakmalı
            issue(9, "Manuel kontrol: Spotify fiyat sayfası okunamıyor"),
            issue(10, "Manuel kontrol: Exxen fiyat sayfası okunamıyor"),
        ]
    )
    page_map = pages()
    page_map.pop(EXXEN_URL)  # Exxen bugün de okunamıyor
    summary, gh, _ = run(root, gemini=FakeGemini(default_answers()), gh=gh, page_map=page_map)
    closed = dict(gh.closed_issues)
    assert set(closed) == {7, 11, 9}
    assert "Sorun düzeldi" in closed[7] and "gemini-test" in closed[7]
    assert "yeniden okundu" in closed[9]
    assert set(summary["kapatilan_issue"]) == {
        "Otomasyon: Gemini erişilemedi",
        "Otomasyon: Gemini anahtarı çalışmıyor",
        "Manuel kontrol: Spotify fiyat sayfası okunamıyor",
    }


def test_local_run_closes_its_own_gemini_issue(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(
        issues=[issue(5, "Otomasyon (yerel): Gemini erişilemedi"), issue(7, "Otomasyon: Gemini erişilemedi")]
    )
    run(root, gemini=FakeGemini(default_answers()), gh=gh, mode=fk.MODE_LOCAL, local_urls={SPOTIFY_URL})
    assert [n for n, _ in gh.closed_issues] == [5]


def test_no_close_when_gemini_still_fails(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(issues=[issue(7, "Otomasyon: Gemini erişilemedi")])
    run(root, gemini=FakeGemini(fail=True), gh=gh)
    assert gh.closed_issues == [] and gh.created_issues == []  # zaten açık, tekrar açılmaz


def test_unreadable_issue_not_closed_without_gemini_answer(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(issues=[issue(9, "Manuel kontrol: Spotify fiyat sayfası okunamıyor")])
    run(root, gemini=FakeGemini(fail=True), gh=gh)  # sayfa indi ama Gemini okumadı
    assert gh.closed_issues == []


def test_close_failure_does_not_crash(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(issues=[issue(7, "Otomasyon: Gemini erişilemedi")], fail_on={"close_issue"})
    summary, _, _ = run(root, gemini=FakeGemini(default_answers()), gh=gh)
    assert any("kapatılamadı" in f for f in summary["basarisiz_islemler"])


def test_local_stale_issue_closes_when_local_run_is_back(tmp_path):
    root = make_root(tmp_path)
    (root / "durum").mkdir()
    (root / "durum" / "yerel-son-calisma.json").write_text(fk.dump_json({"tarih": "2026-11-17"}), encoding="utf-8")
    gh = FakeGitHub(issues=[issue(3, fk.LOCAL_STALE_TITLE)])
    run(root, gemini=FakeGemini(default_answers()), gh=gh, local_urls={SPOTIFY_URL})
    assert [n for n, _ in gh.closed_issues] == [3]


# --- 2 günlük PR hatırlatması (her gün) ---


def fiyat_pr(number, created):
    return {"number": number, "title": "Fiyat", "headRefName": "fiyat/guncelleme", "createdAt": created, "url": "u"}


NOW = dt.datetime(2026, 11, 17, 6, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize(("created", "expect"), [("2026-11-15T05:00:00Z", True), ("2026-11-16T05:00:00Z", False)])
def test_stale_pr_reminder_after_two_days_daily(tmp_path, created, expect):
    root = make_root(tmp_path)
    gh = FakeGitHub(prs=[fiyat_pr(3, created)])
    run(root, gemini=FakeGemini(default_answers()), gh=gh, now=NOW)  # haftalık değil
    titles = [t for t, _ in gh.created_issues]
    assert ("Hatırlatma: fiyat PR'ı #3 2 günden uzun süredir açık" in titles) is expect


def test_stale_pr_reminder_not_in_local_mode(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(prs=[fiyat_pr(3, "2026-11-01T05:00:00Z")])
    run(root, gemini=FakeGemini(default_answers()), gh=gh, now=NOW, mode=fk.MODE_LOCAL, local_urls={SPOTIFY_URL})
    assert gh.created_issues == []


def test_reminder_closes_when_pr_gone_and_is_not_duplicated(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(
        issues=[
            issue(20, "Hatırlatma: fiyat PR'ı #3 7 günden uzun süredir açık"),  # eski eşikle açılmış
            issue(21, "Hatırlatma: fiyat PR'ı #2 2 günden uzun süredir açık"),
        ],
        prs=[fiyat_pr(3, "2026-11-01T05:00:00Z")],
    )
    run(root, gemini=FakeGemini(default_answers()), gh=gh, now=NOW)
    assert [n for n, _ in gh.closed_issues] == [21]  # #2 artık açık değil
    assert gh.created_issues == []  # #3 için zaten hatırlatma var


def test_local_run_closes_unreadable_issue_of_its_own_source(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(
        issues=[
            issue(9, "Manuel kontrol: Spotify fiyat sayfası okunamıyor"),  # yerel kaynak
            issue(10, "Manuel kontrol: Exxen fiyat sayfası okunamıyor"),  # Actions kaynağı
        ]
    )
    run(root, gemini=FakeGemini(default_answers()), gh=gh, mode=fk.MODE_LOCAL, local_urls={SPOTIFY_URL})
    assert [n for n, _ in gh.closed_issues] == [9]
