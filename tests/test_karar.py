"""Yanıt doğrulama, karar, sürüm/değişim alanları ve şema testleri."""

import json

import fiyat_kontrol as fk
import pytest
from helpers import REPO, SPOTIFY_URL, catalog

PAGE = "Bireysel İlk 1 ay boyunca ücretsiz, sonra ayda ₺129.\nAile Sonra ayda ₺199"


def target(key="spotify/bireysel", price=115.0, verified=True, kind="plan"):
    svc, entry = key.split("/")
    return fk.Target(
        key=key,
        kind=kind,
        service_id=None if kind == "paket" else svc,
        entry_id=entry,
        name="Spotify Bireysel",
        group_name="Spotify",
        price=price,
        period="aylik",
        verified=verified,
        url=SPOTIFY_URL,
        note=None,
    )


def ans(price=129, quote="sonra ayda ₺129", changed=True, guven=0.95, periyot="aylik"):
    return {
        "plan_id": "spotify/bireysel",
        "degisti": changed,
        "yeni_fiyat_tl": price,
        "periyot": periyot,
        "kanit_alinti": quote,
        "guven": guven,
    }


# --- halüsinasyon koruması ---


def test_valid_answer_keeps_confidence():
    f = fk.validate_answer(target(), ans(), PAGE)
    assert f.changed and f.new_price == 129
    assert f.confidence == pytest.approx(0.95)
    assert f.reasons == []


def test_quote_not_in_page_drops_confidence():
    f = fk.validate_answer(target(), ans(quote="Bireysel plan artık ayda ₺129"), PAGE)
    assert f.confidence == 0.5
    assert fk.decide(f) == "issue"


def test_price_not_in_quote_drops_confidence():
    f = fk.validate_answer(target(), ans(price=139, quote="sonra ayda ₺129"), PAGE)
    assert f.confidence == 0.5
    assert fk.decide(f) == "issue"


def test_period_mismatch_drops_confidence():
    f = fk.validate_answer(target(), ans(periyot="yillik"), PAGE)
    assert f.confidence == 0.5


def test_inconsistent_degisti_drops_confidence():
    f = fk.validate_answer(target(price=129.0), ans(changed=True), PAGE)
    assert not f.changed
    assert f.confidence == 0.5
    assert fk.decide(f) == "unconfirmed"


def test_missing_price_and_missing_answer():
    f = fk.validate_answer(target(), ans(price=None, quote="", changed=False, guven=0.9), PAGE)
    assert f.confidence <= 0.3 and fk.decide(f) == "unconfirmed"
    f = fk.validate_answer(target(), None, PAGE)
    assert f.confidence == 0.0 and fk.decide(f) == "unconfirmed"


# --- güven eşiği → karar ---


@pytest.mark.parametrize(
    "guven, verified, changed, expected",
    [
        (0.8, True, True, "pr"),
        (0.79, True, True, "issue"),
        (0.95, False, True, "issue_unverified"),
        (0.9, True, False, "ok"),
        (0.6, True, False, "unconfirmed"),
    ],
)
def test_decide(guven, verified, changed, expected):
    price = 129 if changed else 115
    f = fk.validate_answer(
        target(verified=verified),
        ans(price=price, quote=f"sonra ayda ₺{price}", changed=changed, guven=guven),
        PAGE.replace("₺129", f"₺{price}"),
    )
    assert fk.decide(f) == expected


# --- olağandışı işareti ---


@pytest.mark.parametrize(
    "old, new, unusual",
    [(100, 110, False), (100, 300, False), (100, 300.01, True), (100, 400, True), (100, 99.99, True)],
)
def test_is_unusual(old, new, unusual):
    assert fk.is_unusual(old, new) is unusual


# --- değişikliği kataloğa uygulama ---


def finding(key, new_price, kind="plan"):
    t = target(key=key, kind=kind)
    return fk.Finding(t, new_price, True, "alıntı", 0.95, [], SPOTIFY_URL, "gemini-test")


def test_apply_changes_fresh_sets_version_and_change_fields():
    main = catalog()
    cat, applied = fk.apply_changes(main, None, [finding("spotify/bireysel", 129.0)], "2026-11-17")
    assert cat["surum"] == 2 and cat["guncelleme"] == "2026-11-17"
    p = fk.find_entry(cat, applied[0].finding.target)
    assert p["fiyat_tl"] == 129 and isinstance(p["fiyat_tl"], int)
    assert p["onceki_fiyat_tl"] == 115
    assert p["degisim_turu"] == "zam"
    assert p["degisim_surumu"] == 2
    assert p["gecerlilik"] == "2026-11-17"
    assert p["kontrol_tarihi"] == "2026-11-17"
    assert p["dogrulandi"] is True
    assert main["surum"] == 1  # main kopyası değişmez


def test_apply_changes_decrease_is_indirim():
    cat, applied = fk.apply_changes(catalog(), None, [finding("spotify/aile", 189.5)], "2026-11-17")
    assert applied[0].change_type == "indirim" and applied[0].unusual
    assert fk.find_entry(cat, applied[0].finding.target)["degisim_turu"] == "indirim"


def test_apply_changes_package_updates_only_package_fields():
    cat, applied = fk.apply_changes(
        catalog(), None, [finding("paket/turkcell-x", 550.0, kind="paket")], "2026-11-17"
    )
    pkg = cat["operator_paketleri"][0]
    assert pkg["fiyat_tl"] == 550 and pkg["kontrol_tarihi"] == "2026-11-17"
    assert "degisim_turu" not in pkg and "onceki_fiyat_tl" not in pkg
    assert fk.validate_catalog(cat, load_schema()) == []


def test_apply_changes_to_open_pr_keeps_branch_version_and_skips_duplicates():
    main = catalog()
    branch, _ = fk.apply_changes(main, None, [finding("spotify/bireysel", 125.0)], "2026-11-16")
    assert branch["surum"] == 2
    # Ertesi gün: bireysel 129'a çıktı, aile 219 oldu; turkcell-x zaten PR'daki fiyatta değil.
    branch2, applied = fk.apply_changes(
        main, branch, [finding("spotify/bireysel", 129.0), finding("spotify/aile", 219.0)], "2026-11-17"
    )
    assert branch2["surum"] == 2  # açık PR'ın sürümü korunur
    bireysel = fk.find_entry(branch2, applied[0].finding.target)
    assert bireysel["fiyat_tl"] == 129 and bireysel["onceki_fiyat_tl"] == 115  # eski = yayındaki
    assert bireysel["degisim_surumu"] == 2
    # Aynı değişiklik PR'da zaten varsa tekrar eklenmez.
    _, again = fk.apply_changes(main, branch2, [finding("spotify/aile", 219.0)], "2026-11-18")
    assert again == []


def test_apply_changes_branch_without_bump_gets_bumped():
    main = catalog()
    branch = catalog()  # dal main ile aynı sürümde (ör. elle açılmış PR)
    cat, _ = fk.apply_changes(main, branch, [finding("spotify/aile", 219.0)], "2026-11-17")
    assert cat["surum"] == 2


# --- şema ---


def load_schema():
    return json.loads((REPO / "sema" / "fiyatlar.schema.json").read_text(encoding="utf-8"))


@pytest.mark.veri
def test_real_catalog_passes_schema():
    cat = json.loads((REPO / "fiyatlar.json").read_text(encoding="utf-8"))
    assert fk.validate_catalog(cat, load_schema()) == []


def test_schema_errors_are_reported():
    cat = catalog()
    cat["servisler"][0]["planlar"][0]["fiyat_tl"] = -5
    cat["operator_paketleri"][0]["icerir"].append({"servis": "yok-boyle", "plan": None})
    errors = fk.validate_catalog(cat, load_schema())
    assert any("fiyat_tl" in e for e in errors)
    assert any("yok-boyle" in e for e in errors)


def test_dump_json_format():
    expected = "\n".join(["{", ' "a": [', "  1,", "  {", '   "b": "ç"', "  }", " ]", "}", ""])
    assert fk.dump_json({"a": [1, {"b": "ç"}]}) == expected


@pytest.mark.veri
def test_dump_json_matches_repo_format():
    raw = (REPO / "fiyatlar.json").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert fk.dump_json(json.loads(raw)) == raw


# --- ardışık hata sayacı ---


def test_bump_counter_counts_days_not_runs():
    bucket = {}
    assert fk.bump_counter(bucket, "u", "2026-11-15", "HTTP 503") == 1
    assert fk.bump_counter(bucket, "u", "2026-11-15", "HTTP 503") == 1
    assert fk.bump_counter(bucket, "u", "2026-11-16", "HTTP 503") == 2
    assert fk.bump_counter(bucket, "u", "2026-11-17", "HTTP 503") == 3
    fk.reset_counter(bucket, "u")
    assert bucket == {}


def test_fmt_helpers():
    assert fk.fmt_tl(1199.99) == "1.199,99 TL"
    assert fk.fmt_tl(115) == "115 TL"
    assert fk.fmt_pct(12.345) == "+12,3%"
    assert fk.json_price(129.0) == 129 and fk.json_price(129.999) == 130
