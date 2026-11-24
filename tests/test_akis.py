"""Uçtan uca akış testleri (sahte HTTP, Gemini, gh ve git ile)."""

import datetime as dt
import json

import fiyat_kontrol as fk
from helpers import (
    EXXEN_URL,
    SPOTIFY_URL,
    TURKCELL_URL,
    FakeGemini,
    FakeGit,
    FakeGitHub,
    answer,
    catalog,
    default_answers,
    make_root,
    pages,
    published_catalog,
    run,
)


def spotify_hike(guven=0.95, aile=199):
    return {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True, guven),
            answer("spotify/aile", aile, f"Sonra ayda ₺{aile}", aile != 199),
        ]
    }


def test_one_gemini_request_per_url(tmp_path):
    root = make_root(tmp_path)
    gemini = FakeGemini(default_answers())
    summary, gh, git = run(root, gemini=gemini)
    # Doğrulanan kaynaklar bir kez sorulur; Turkcell örneğinde paket adı sayfada
    # olmadığından 'unconfirmed' kalır ve yalnız o bir kez yeniden sorulur.
    assert sorted(gemini.calls) == sorted([SPOTIFY_URL, EXXEN_URL, TURKCELL_URL, TURKCELL_URL])
    assert gh.created_prs == [] and gh.created_issues == []
    assert summary["model"] == "gemini-test"


def test_confident_change_opens_pr_with_evidence(tmp_path):
    root = make_root(tmp_path)
    gemini = FakeGemini(default_answers(**spotify_hike()))
    _, gh, git = run(root, gemini=gemini, page_map=pages(b="129"))
    assert len(gh.created_prs) == 1 and gh.created_issues == []
    pr = gh.created_prs[0]
    assert pr["branch"] == "fiyat/guncelleme"
    assert "katalog sürümü 2" in pr["title"] and "olağandışı" not in pr["title"]
    assert pr["labels"] == []
    for text in ("115 TL", "129 TL", "+12,2%", "sonra ayda ₺129", SPOTIFY_URL, "gemini-test"):
        assert text in pr["body"]
    cat = published_catalog(git)
    p = cat["servisler"][0]["planlar"][0]
    assert (p["fiyat_tl"], p["onceki_fiyat_tl"], p["degisim_turu"], p["degisim_surumu"]) == (
        129,
        115,
        "zam",
        2,
    )
    assert git.published[0]["from_existing"] is False
    # main'deki fiyatlar.json'a dokunulmaz
    assert json.loads((root / "fiyatlar.json").read_text(encoding="utf-8"))["surum"] == 1


def test_change_is_added_to_existing_open_pr(tmp_path):
    root = make_root(tmp_path)
    branch_cat, _ = fk.apply_changes(
        catalog(),
        None,
        [fk.Finding(fk.collect_targets(catalog())[1], 219.0, True, "q", 0.9, [], SPOTIFY_URL, "m")],
        "2026-11-16",
    )
    git = FakeGit({"fiyatlar.json": fk.dump_json(branch_cat)})
    gh = FakeGitHub(
        prs=[
            {
                "number": 7,
                "title": "Fiyat güncellemesi (katalog sürümü 2)",
                "body": "Önceki gövde",
                "headRefName": "fiyat/guncelleme",
                "createdAt": "2026-11-16T06:00:00Z",
                "url": "u",
            }
        ]
    )
    gemini = FakeGemini(default_answers(**spotify_hike(aile=219)))
    _, gh, git = run(root, gemini=gemini, page_map=pages(b="129", a="219"), gh=gh, git=git)
    assert gh.created_prs == []
    assert len(gh.edited_prs) == 1
    edit = gh.edited_prs[0]
    assert edit["number"] == 7 and edit["body"].startswith("Önceki gövde")
    assert "Spotify Bireysel" in edit["body"] and "Spotify Aile" not in edit["body"]  # aile zaten PR'da
    assert git.published[0]["from_existing"] is True
    cat = published_catalog(git)
    assert cat["surum"] == 2
    assert [p["fiyat_tl"] for p in cat["servisler"][0]["planlar"]] == [129, 219]


def test_low_confidence_change_opens_single_issue(tmp_path):
    root = make_root(tmp_path)
    gemini = FakeGemini(default_answers(**spotify_hike(guven=0.7)))
    gh = FakeGitHub()
    run(root, gemini=gemini, page_map=pages(b="129"), gh=gh)
    assert gh.created_prs == []
    assert [t for t, _ in gh.created_issues] == ["Manuel kontrol: Spotify Bireysel"]
    # Ertesi gün aynı başlıkta açık issue var → yenisi açılmaz.
    run(root, day="2026-11-18", gemini=gemini, page_map=pages(b="129"), gh=gh)
    assert len(gh.created_issues) == 1


def test_hallucinated_quote_never_opens_pr(tmp_path):
    root = make_root(tmp_path)
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 149, "Bireysel artık ayda ₺149", True, 0.99),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }
    gh = FakeGitHub()
    run(root, gemini=FakeGemini(default_answers(**fake)), gh=gh)  # sayfa hâlâ ₺115
    assert gh.created_prs == []
    assert [t for t, _ in gh.created_issues] == ["Manuel kontrol: Spotify Bireysel"]


def test_unverified_plan_change_opens_issue_not_pr(tmp_path):
    root = make_root(tmp_path)
    fake = {EXXEN_URL: [answer("exxen/reklamli", 299.9, "Reklamlı paket aylık 299,90 TL", True, 0.97)]}
    gh = FakeGitHub()
    _, gh, git = run(root, gemini=FakeGemini(default_answers(**fake)), page_map=pages(r="299,90"), gh=gh)
    assert gh.created_prs == [] and git.published == []
    title, body = gh.created_issues[0]
    assert title == "Manuel kontrol: Exxen Reklamlı" and "tahmini" in body


def test_unusual_change_is_flagged(tmp_path):
    root = make_root(tmp_path)
    fake = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 115, "sonra ayda ₺115", False),
            answer("spotify/aile", 179, "Sonra ayda ₺179", True),
        ]
    }
    _, gh, _ = run(root, gemini=FakeGemini(default_answers(**fake)), page_map=pages(a="179"))
    pr = gh.created_prs[0]
    assert pr["title"].startswith("⚠️ olağandışı")
    assert pr["labels"] == [fk.UNUSUAL_LABEL]
    assert "indirim" in pr["body"]


def test_schema_failure_opens_issue_instead_of_pr(tmp_path):
    cat = catalog()
    cat["servisler"][0]["planlar"][1]["kontrol_tarihi"] = "dün"  # main zaten bozuk
    root = make_root(tmp_path, cat)
    _, gh, git = run(root, gemini=FakeGemini(default_answers(**spotify_hike())), page_map=pages(b="129"))
    assert gh.created_prs == [] and git.published == []
    title, body = gh.created_issues[0]
    assert title == "Otomasyon: fiyat güncellemesi şema doğrulamasından geçmedi"
    assert "kontrol_tarihi" in body


def test_read_failure_issue_on_third_consecutive_day(tmp_path):
    root = make_root(tmp_path)
    broken = pages()
    broken[TURKCELL_URL] = ""  # indirilemez
    gh = FakeGitHub()
    gemini = FakeGemini(default_answers())
    title = "Manuel kontrol: Turkcell X fiyat sayfası okunamıyor"
    for day in ("2026-11-15", "2026-11-16"):
        run(root, day=day, gemini=gemini, page_map=broken, gh=gh)
        assert gh.created_issues == []
    run(root, day="2026-11-16", gemini=gemini, page_map=broken, gh=gh)  # aynı gün tekrar: sayılmaz
    assert gh.created_issues == []
    run(root, day="2026-11-17", gemini=gemini, page_map=broken, gh=gh)
    assert [t for t, _ in gh.created_issues] == [title]
    state = json.loads((root / "durum" / "okuma-hatalari.json").read_text(encoding="utf-8"))
    assert state["kaynaklar"][TURKCELL_URL]["ardisik"] == 3
    # Başarılı okuma sayacı sıfırlar.
    run(root, day="2026-11-18", gemini=gemini, gh=gh)
    state = json.loads((root / "durum" / "okuma-hatalari.json").read_text(encoding="utf-8"))
    assert TURKCELL_URL not in state["kaynaklar"]


def test_page_without_lira_counts_as_read_failure(tmp_path):
    root = make_root(tmp_path)
    page_map = pages()
    page_map[SPOTIFY_URL] = "<html><body><p>Premium Individual $11.99/month</p></body></html>"
    gemini = FakeGemini(default_answers())
    summary, _, _ = run(root, gemini=gemini, page_map=page_map)
    spotify = next(k for k in summary["kaynaklar"] if k["url"] == SPOTIFY_URL)
    assert spotify["durum"] == "okunamadi" and "TL" in spotify["ayrinti"]
    assert SPOTIFY_URL not in gemini.calls


def test_unconfirmed_plan_issue_after_three_days(tmp_path):
    root = make_root(tmp_path)
    fake = {TURKCELL_URL: [answer("paket/turkcell-x", None, "", False, 0.2)]}
    gh = FakeGitHub()
    for i, day in enumerate(("2026-11-15", "2026-11-16", "2026-11-17")):
        run(root, day=day, gemini=FakeGemini(default_answers(**fake)), gh=gh)
        assert len(gh.created_issues) == (1 if i == 2 else 0)
    assert gh.created_issues[0][0] == "Manuel kontrol: Turkcell X"


def test_gemini_unavailable_falls_back_to_page_fingerprint(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    run(root, day="2026-11-15", gemini=FakeGemini(default_answers()), gh=gh)  # karma kaydedilir
    failing = FakeGemini(fail=True)
    run(root, day="2026-11-16", gemini=failing, gh=gh)  # fiyatlar aynı → yalnız genel uyarı
    assert [t for t, _ in gh.created_issues] == ["Otomasyon: Gemini erişilemedi"]
    run(root, day="2026-11-17", gemini=failing, page_map=pages(a="219"), gh=gh)
    titles = [t for t, _ in gh.created_issues]
    assert "Manuel kontrol: Spotify fiyat sayfası değişti" in titles
    assert gh.created_prs == []


def test_dry_run_writes_nothing(tmp_path):
    root = make_root(tmp_path)
    before = (root / "fiyatlar.json").read_text(encoding="utf-8")
    gh = fk.GitHub(root, dry_run=True, log=lambda m: None)
    git = fk.Git(root, dry_run=True, log=lambda m: None)
    summary, _, _ = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129"),
        gh=gh,
        git=git,
        weekly=True,
        dry_run=True,
    )
    assert not (root / "durum").exists()
    assert (root / "fiyatlar.json").read_text(encoding="utf-8") == before
    assert summary["pr"].startswith("Yeni PR")


def test_weekly_tasks(tmp_path):
    guides = {
        "sema_surumu": 1,
        "surum": 1,
        "guncelleme": "2026-11-01",
        "rehberler": [
            {
                "servis": "spotify",
                "notlar": None,
                "yollar": [
                    {
                        "kanal": "web",
                        "adimlar": ["Hesap > İptal"],
                        "kaynak": "https://kirik.example/iptal",
                        "kontrol_tarihi": "2026-11-01",
                    },
                    {
                        "kanal": "web",
                        "adimlar": ["Hesap > İptal"],
                        "kaynak": "https://saglam.example/iptal",
                        "kontrol_tarihi": "2026-11-01",
                    },
                ],
            }
        ],
    }
    root = make_root(tmp_path, guides=guides)
    gh = FakeGitHub(
        issues=[{"number": 5, "title": "İzlenemiyor: izleme_url'si olmayan kayıtlar", "body": "eski"}],
        prs=[
            {
                "number": 3,
                "title": "Fiyat güncellemesi",
                "body": "",
                "headRefName": "fiyat/guncelleme",
                "createdAt": "2026-11-01T06:00:00Z",
                "url": "https://github.com/x/pull/3",
            },
            {
                "number": 4,
                "title": "Başka",
                "body": "",
                "headRefName": "duzeltme",
                "createdAt": "2026-10-01T06:00:00Z",
                "url": "u",
            },
        ],
    )
    now = dt.datetime(2026, 11, 17, 6, tzinfo=dt.timezone.utc)
    _, gh, git = run(
        root,
        gemini=FakeGemini(default_answers()),
        gh=gh,
        weekly=True,
        links={"https://kirik.example/iptal": "HTTP 404"},
        now=now,
    )
    assert gh.edited_issues and gh.edited_issues[0][0] == 5
    assert "hbo-max/standart" in gh.edited_issues[0][1]
    titles = [t for t, _ in gh.created_issues]
    assert "Kırık iptal rehberi linki: spotify" in titles
    assert "Hatırlatma: fiyat PR'ı #3 2 günden uzun süredir açık" in titles
    assert not any("#4" in t for t in titles)
    heartbeat = json.loads((root / "durum" / "son-calisma.json").read_text(encoding="utf-8"))
    assert heartbeat["tarih"] == "2026-11-17" and heartbeat["model"] == "gemini-test"
    assert heartbeat["kontrol_edilen_kaynak"] == 3
    assert "durum/son-calisma.json" in git.main_commits[-1]


def test_heartbeat_not_written_on_daily_run(tmp_path):
    root = make_root(tmp_path)
    run(root, gemini=FakeGemini(default_answers()))
    assert not (root / "durum" / "son-calisma.json").exists()


class SequenceGemini(FakeGemini):
    """Aynı URL'ye art arda farklı yanıtlar (ikinci sorgu testleri)."""

    def __init__(self, first, second):
        super().__init__(first)
        self.second = second

    def generate_json(self, prompt, schema):
        data = super().generate_json(prompt, schema)
        if self.calls.count(self.calls[-1]) > 1:
            return {"planlar": self.second.get(self.calls[-1], [])}
        return data


def _bad_aile():
    # Değişmemiş fiyat ama alıntı sayfada yok → unconfirmed (2026-11-16 iCloud vakası).
    return {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 115, "sonra ayda ₺115", False),
            answer("spotify/aile", 199, "Aile planı ayda ₺199", False),
        ]
    }


def _decisions(summary):
    return {d["kayit"]: d for k in summary["kaynaklar"] for d in k["kararlar"]}


def test_unconfirmed_is_retried_once_and_upgraded_to_ok(tmp_path):
    root = make_root(tmp_path)
    gemini = SequenceGemini(default_answers(**_bad_aile()), default_answers())
    summary, gh, _ = run(root, gemini=gemini)
    assert gemini.calls.count(SPOTIFY_URL) == 2
    assert gemini.calls.count(EXXEN_URL) == 1  # sorunsuz kaynak yeniden sorulmaz
    d = _decisions(summary)["spotify/aile"]
    assert d["karar"] == "ok" and "İkinci sorguda doğrulandı." in d["nedenler"]
    assert gh.created_prs == [] and gh.created_issues == []


def test_retry_never_turns_into_pr_or_changes_other_decisions(tmp_path):
    root = make_root(tmp_path)
    # İkinci yanıt "zam" iddia etse bile (sayfa ₺199) yalnız ok yükseltmesi kullanılır.
    second = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True, 0.99),
            answer("spotify/aile", 219, "Sonra ayda ₺219", True, 0.99),
        ]
    }
    gemini = SequenceGemini(default_answers(**_bad_aile()), default_answers(**second))
    summary, gh, git = run(root, gemini=gemini)
    d = _decisions(summary)
    assert d["spotify/aile"]["karar"] == "unconfirmed"
    assert d["spotify/aile"]["alinti"] == "Aile planı ayda ₺199"  # teşhis için loglanır
    assert d["spotify/bireysel"]["karar"] == "ok"
    assert gh.created_prs == [] and git.published == []


class SecondCallFails(FakeGemini):
    def generate_json(self, prompt, schema):
        url_calls_before = len(self.calls)
        data = super().generate_json(prompt, schema)
        if self.calls.count(self.calls[-1]) > 1 and url_calls_before:
            raise fk.GeminiUnavailable("HTTP 429 (gemini-test)")
        return data


def test_retry_failure_keeps_first_result_and_is_not_an_error(tmp_path):
    root = make_root(tmp_path)
    gemini = SecondCallFails(default_answers(**_bad_aile()))
    summary, gh, _ = run(root, gemini=gemini)
    assert gemini.calls.count(SPOTIFY_URL) == 2
    assert summary["hata"] == 0
    assert _decisions(summary)["spotify/aile"]["karar"] == "unconfirmed"
    assert gh.created_prs == []
