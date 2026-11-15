"""F1.4 denetim bulgularının testleri: plan bağlama, periyot, kampanya, bayat PR, hata toleransı."""

import datetime as dt
import json

import fiyat_kontrol as fk
import pytest
from helpers import (
    SPOTIFY_URL,
    FakeGemini,
    FakeGit,
    FakeGitHub,
    answer,
    catalog,
    default_answers,
    make_root,
    pages,
    plan,
    run,
)

YT = "https://www.youtube.com/premium?hl=tr&gl=TR"
YT_PAGE = "\n".join(
    [
        "Aylık planlar",
        "Premium Lite Bireysel İlk ay ₺0 • Ardından ₺79,99/ay",
        "Premium Bireysel İlk ay ₺0 • Ardından ₺119,99/ay",
        "Öğrenci İlk ay ₺0 • Ardından ₺79,99/ay",
        "Aile İlk ay ₺0 • Ardından ₺239,99/ay",
    ]
)
LITE_Q = "Premium Lite Bireysel İlk ay ₺0 • Ardından ₺79,99/ay"
BIREYSEL_Q = "Premium Bireysel İlk ay ₺0 • Ardından ₺119,99/ay"
OGRENCI_Q = "Öğrenci İlk ay ₺0 • Ardından ₺79,99/ay"
AILE_Q = "Aile İlk ay ₺0 • Ardından ₺239,99/ay"


def youtube_targets():
    cat = {
        "servisler": [
            {
                "id": "youtube-premium",
                "ad": "YouTube Premium",
                "kategori": "video",
                "planlar": [
                    plan("lite", "Premium Lite", 1, 79.99, YT),
                    plan("bireysel", "Bireysel", 2, 119.99, YT),
                    plan("ogrenci", "Öğrenci", 2, 79.99, YT),
                    plan("aile", "Aile", 3, 239.99, YT),
                ],
            }
        ],
        "operator_paketleri": [],
    }
    return fk.collect_targets(cat)


def yt_answers(**override):
    data = {
        "lite": answer("youtube-premium/lite", 79.99, LITE_Q, False),
        "bireysel": answer("youtube-premium/bireysel", 119.99, BIREYSEL_Q, False),
        "ogrenci": answer("youtube-premium/ogrenci", 79.99, OGRENCI_Q, False),
        "aile": answer("youtube-premium/aile", 239.99, AILE_Q, False),
    }
    data.update(override)
    return {a["plan_id"]: a for a in data.values()}


def by_plan(findings):
    return {f.target.entry_id: f for f in findings}


# --- 1. alıntı plana bağlanmalı ---


def test_youtube_lite_and_student_same_price_are_both_bound():
    findings = by_plan(fk.validate_answers(youtube_targets(), yt_answers(), YT_PAGE))
    for key in ("lite", "bireysel", "ogrenci", "aile"):
        assert findings[key].confidence == pytest.approx(0.95), (key, findings[key].reasons)
        assert fk.decide(findings[key]) == "ok"


def test_bireysel_using_lite_quote_is_rejected():
    wrong = answer("youtube-premium/bireysel", 79.99, LITE_Q, True, 0.97)
    findings = by_plan(fk.validate_answers(youtube_targets(), yt_answers(bireysel=wrong), YT_PAGE))
    assert fk.decide(findings["bireysel"]) == "issue"  # PR değil
    assert findings["lite"].confidence == 0.5  # alıntı artık tek başına kanıt değil


def test_student_using_lite_quote_is_rejected():
    wrong = answer("youtube-premium/ogrenci", 79.99, LITE_Q, False, 0.97)
    findings = by_plan(fk.validate_answers(youtube_targets(), yt_answers(ogrenci=wrong), YT_PAGE))
    assert findings["ogrenci"].confidence == 0.5
    assert any("adı geçmiyor" in r for r in findings["ogrenci"].reasons)


def spotify_targets():
    cat = catalog()
    cat["servisler"][0]["planlar"].append(plan("duo", "Duo", 2, 159, SPOTIFY_URL))
    return [t for t in fk.collect_targets(cat) if t.url == SPOTIFY_URL]


def test_duo_with_individual_quote_is_not_a_pr():
    page = "Bireysel ₺59,99/ay\nAile ₺199/ay\nDuo ₺159/ay"
    answers = {
        "spotify/bireysel": answer("spotify/bireysel", 59.99, "Bireysel ₺59,99/ay", True),
        "spotify/aile": answer("spotify/aile", 199, "Aile ₺199/ay", False),
        "spotify/duo": answer("spotify/duo", 59.99, "Bireysel ₺59,99/ay", True, 0.99),
    }
    findings = by_plan(fk.validate_answers(spotify_targets(), answers, page))
    assert fk.decide(findings["duo"]) == "issue"
    assert findings["duo"].confidence == 0.5


def test_same_quote_with_different_prices_flags_both():
    page = "Bireysel ve Aile planı ₺129/ay"
    answers = {
        "spotify/bireysel": answer("spotify/bireysel", 129, "Bireysel ve Aile planı ₺129/ay", True),
        "spotify/aile": answer("spotify/aile", 199, "Bireysel ve Aile planı ₺129/ay", False),
    }
    findings = by_plan(fk.validate_answers(spotify_targets()[:2], answers, page))
    assert findings["bireysel"].confidence == 0.5
    assert findings["aile"].confidence <= 0.5


def test_numbered_family_plans_are_not_mixed():
    url = "https://www.storytel.com/tr"
    cat = {
        "servisler": [
            {
                "id": "storytel",
                "ad": "Storytel",
                "kategori": "kitap",
                "planlar": [
                    plan("aile-2", "Aile (2 hesap)", 2, 499.99, url),
                    plan("aile-3", "Aile (3 hesap)", 3, 626.99, url),
                ],
            }
        ],
        "operator_paketleri": [],
    }
    page = "Aile 2 hesap ₺499,99/ay\nAile 3 hesap ₺626,99/ay"
    answers = {
        "storytel/aile-2": answer("storytel/aile-2", 626.99, "Aile 3 hesap ₺626,99/ay", True, 0.95),
        "storytel/aile-3": answer("storytel/aile-3", 626.99, "Aile 3 hesap ₺626,99/ay", False),
    }
    findings = by_plan(fk.validate_answers(fk.collect_targets(cat), answers, page))
    assert fk.decide(findings["aile-2"]) == "issue"


def test_page_window_binds_single_package_quote():
    # Paket sayfasında adı fiyat cümlesinin hemen önünde; alıntıda geçmese de bağlanır.
    target = [t for t in fk.collect_targets(catalog()) if t.kind == "paket"]
    page = "Turkcell X\n12 ay taahhütle aylık 550TL, taahhütsüz 750TL"
    answers = {"paket/turkcell-x": answer("paket/turkcell-x", 550, "12 ay taahhütle aylık 550TL", True)}
    (f,) = fk.validate_answers(target, answers, page)
    assert f.confidence == pytest.approx(0.95) and fk.decide(f) == "pr"


# --- 2. periyot ---


def test_null_period_drops_confidence():
    t = spotify_targets()[0]
    a = answer("spotify/bireysel", 129, "Bireysel ₺129/ay", True, periyot=None)
    f = fk.validate_answer(t, a, "Bireysel ₺129/ay")
    assert f.confidence == 0.5


@pytest.mark.parametrize(
    "quote, ok",
    [
        ("Bireysel ₺129/ay", True),
        ("Bireysel aylık ₺129", True),
        ("Bireysel ₺129/yıl", False),
        ("Bireysel yıllık ₺129", False),
        ("Bireysel haftalık ₺129", False),
    ],
)
def test_period_words_in_quote(quote, ok):
    t = spotify_targets()[0]
    f = fk.validate_answer(t, answer("spotify/bireysel", 129, quote, True), quote)
    assert (f.confidence > 0.8) is ok, f.reasons


# --- 3. alıntı uzunluğu ve para birimi ---


def test_long_quote_drops_confidence():
    quote = "Bireysel " + "çok güzel bir plan " * 6 + "₺129/ay"
    t = spotify_targets()[0]
    f = fk.validate_answer(t, answer("spotify/bireysel", 129, quote, True), quote)
    assert f.confidence == 0.5 and any("kelimeden uzun" in r for r in f.reasons)


def test_bare_number_without_currency_is_not_enough():
    quote = "Bireysel planı ayda 129 öde"
    t = spotify_targets()[0]
    f = fk.validate_answer(t, answer("spotify/bireysel", 129, quote, True), quote)
    assert f.confidence == 0.5
    assert not fk.price_in_quote(129, quote)
    assert fk.price_in_quote(129, "ayda 129 TL")


# --- 4. kampanya / ilk ay / eski fiyat ---


@pytest.mark.parametrize(
    "quote, price, ok",
    [
        ("Bireysel İlk ay ₺0 • Ardından ₺79,99/ay", 79.99, True),
        ("Bireysel İlk 1 ay boyunca ücretsiz, sonra ayda ₺79,99", 79.99, True),
        ("Bireysel İlk 3 ay ₺49,99/ay", 49.99, False),
        ("Bireysel kampanyalı fiyat ₺49,99/ay", 49.99, False),
        ("Bireysel ₺99 yerine ₺79/ay", 79, False),
        ("Bireysel ₺99/ay yerine ₺79", 99, False),
        ("Bireysel 3 ay boyunca ₺49,99/ay", 49.99, False),
        ("Bireysel ₺0 ₺79,99/ay", 79.99, False),
        ("Bireysel (eski fiyat: ₺99) ₺79/ay", 79, False),
        ("Bireysel ile %33 tasarruf edin* Premium Bireysel Aylık ₺79/ay", 79, True),
        ("Bireysel kampanyalı ₺49/ay", 49, False),
    ],
)
def test_campaign_prices_are_rejected(quote, price, ok):
    t = spotify_targets()[0]
    f = fk.validate_answer(t, answer("spotify/bireysel", price, quote, True), quote)
    assert (f.confidence > 0.8) is ok, f.reasons


def test_strikethrough_prices_are_marked():
    html = "<p>Bireysel <del>₺99</del> ₺79/ay</p><p>Aile <s>199 TL</s> 149 TL</p>"
    text = fk.extract_page_text(html)
    assert "(eski fiyat: ₺99)" in text
    assert "(eski fiyat: 199 TL)" in text


# --- 5. fiyat biçimleri ---


def test_price_formats():
    text = "A 259,99₺ B 259,99 ₺ C TL 500 D TRY 1.199,99 E ₺119,99 F 75TL G 50 TL 500 dakika"
    assert fk.price_tokens(text) == sorted({"259,99₺", "TL500", "TRY1.199,99", "₺119,99", "75TL", "50TL"})
    assert not fk.has_price('{"value":"TL","label":"Timor-Leste"} TLT 500')
    assert fk.price_in_quote(259.99, "Aylık 259,99 ₺")
    assert fk.price_in_quote(500, "Paket fiyatı TL 500")


# --- 6. açık PR'daki bayat fiyat ---


def stale_setup(tmp_path):
    root = make_root(tmp_path)
    finding = fk.Finding(fk.collect_targets(catalog())[0], 129.0, True, "q", 0.9, [], SPOTIFY_URL, "m")
    branch_cat, _ = fk.apply_changes(catalog(), None, [finding], "2026-11-16")
    git = FakeGit({"fiyatlar.json": fk.dump_json(branch_cat)})
    gh = FakeGitHub(
        prs=[
            {
                "number": 9,
                "title": "Fiyat güncellemesi (katalog sürümü 2)",
                "body": "gövde",
                "headRefName": "fiyat/guncelleme",
                "createdAt": "2026-11-16T06:00:00Z",
                "url": "u",
            }
        ]
    )
    return root, gh, git


def test_stale_open_pr_gets_one_warning(tmp_path):
    root, gh, git = stale_setup(tmp_path)
    # Sayfa yine 115 TL gösteriyor (PR'da 129 TL var).
    run(root, gemini=FakeGemini(default_answers()), gh=gh, git=git)
    assert len(gh.comments[9]) == 1
    assert "sayfa artık 115 TL" in gh.comments[9][0] and "129 TL" in gh.comments[9][0]
    assert gh.created_prs == [] and gh.edited_prs == []
    run(root, day="2026-11-18", gemini=FakeGemini(default_answers()), gh=gh, git=git)
    assert len(gh.comments[9]) == 1  # aynı uyarı tekrarlanmaz


def test_matching_open_pr_gets_no_warning(tmp_path):
    root, gh, git = stale_setup(tmp_path)
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }
    run(root, gemini=FakeGemini(default_answers(**fake)), page_map=pages(b="129"), gh=gh, git=git)
    assert gh.comments == {}


# --- düşük öncelikli bulgular ---


def test_gemini_error_detail_not_in_issue(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    run(root, gemini=FakeGemini(fail=True), gh=gh)
    title, body = gh.created_issues[0]
    assert title == "Otomasyon: Gemini erişilemedi"
    assert "HTTP 429 (gemini-test)" in body
    assert "Quota exceeded" not in body and "123456" not in body


def test_quotes_are_code_spans_in_issue_and_pr(tmp_path):
    root = make_root(tmp_path)
    quote = "Sonra ayda ₺129 @musa **kalın**"
    page_map = pages()
    page_map[SPOTIFY_URL] = (
        f"<html><body><h2>Bireysel</h2><p>{quote}</p><p>Aile Sonra ayda ₺199</p></body></html>"
    )
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, quote, True),
            answer("spotify/aile", 199, "Aile Sonra ayda ₺199", False),
        ]
    }
    _, gh, _ = run(root, gemini=FakeGemini(default_answers(**fake)), page_map=page_map)
    assert f"`{quote}`" in gh.created_prs[0]["body"]
    assert fk.code_span("a `b` c") == "``a `b` c``"


def test_prompt_uses_random_boundary():
    t = fk.collect_targets(catalog())[:1]
    a = fk.build_prompt("https://x", t, "metin ₺1")
    b = fk.build_prompt("https://x", t, "metin ₺1")
    assert "<<<" not in a
    boundary = a.split("BAŞLA ")[1].split()[0]
    assert boundary.startswith("SAYFA-") and boundary not in b
    assert f"BİTİR {boundary}" in a


def test_github_failure_does_not_stop_run(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(fail_on={"create_issue"})
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True, 0.6),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }
    broken = pages(b="129")
    broken["https://www.turkcell.com.tr/paket/x"] = ""
    summary, _, git = run(root, gemini=FakeGemini(default_answers(**fake)), page_map=broken, gh=gh)
    assert summary["basarisiz_islemler"]  # çıkış kodu 1 olur
    state = json.loads((root / "durum" / "okuma-hatalari.json").read_text(encoding="utf-8"))
    assert state["kaynaklar"]  # sayaçlar yine yazıldı
    assert git.main_commits


def test_unknown_open_pr_state_blocks_new_pr(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(fail_on={"find_open_pr"})
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }
    summary, gh, git = run(root, gemini=FakeGemini(default_answers(**fake)), page_map=pages(b="129"), gh=gh)
    assert gh.created_prs == [] and git.published == []
    assert any("açık fiyat PR'ı okunamadı" in x for x in summary["basarisiz_islemler"])


def test_main_returns_nonzero_on_failures(monkeypatch, tmp_path):
    class FailingRunner:
        def __init__(self, *a, **k):
            pass

        def execute(self):
            return {
                "tarih": "2026-11-17",
                "model": None,
                "kaynaklar": [],
                "pr": "",
                "acilan_issue": [],
                "guncellenen_issue": [],
                "zaten_acik_issue": [],
                "hata": 0,
                "basarisiz_islemler": ["issue açılamadı: X (RuntimeError)"],
                "bastirilan_tespitler": [],
            }

    monkeypatch.setattr(fk, "Runner", FailingRunner)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert fk.main(["--tarih", "2026-11-17"]) == 1


NOW = dt.datetime(2026, 11, 17, 6, tzinfo=dt.timezone.utc)


def flagged(price, closed_at):
    return {"body": f"... {fk.detection_marker('spotify/bireysel', price)} ...", "closedAt": closed_at}


def hike():
    return {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }


def test_false_positive_label_suppresses_for_30_days(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(closed_flagged=[flagged(129, "2026-11-10T08:00:00Z")])
    summary, gh, git = run(
        root, gemini=FakeGemini(default_answers(**hike())), page_map=pages(b="129"), gh=gh, now=NOW
    )
    assert gh.created_prs == [] and gh.created_issues == []
    assert summary["bastirilan_tespitler"] == ["spotify/bireysel=129.00"]


def test_old_or_different_false_positive_does_not_suppress(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub(
        closed_flagged=[flagged(129, "2026-09-01T08:00:00Z"), flagged(135, "2026-11-10T08:00:00Z")]
    )
    _, gh, _ = run(
        root, gemini=FakeGemini(default_answers(**hike())), page_map=pages(b="129"), gh=gh, now=NOW
    )
    assert len(gh.created_prs) == 1
    assert fk.detection_marker("spotify/bireysel", 129) in gh.created_prs[0]["body"]
