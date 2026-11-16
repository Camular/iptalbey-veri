"""Değişmemiş fiyatın onayı (yanlış 'unconfirmed' azaltma) ve yanlış PR korumasının sürdüğü.

Sayfa parçaları 2026-11-16'da resmi sayfalardan `extract_page_text` ile alınan metinden
kısaltılmıştır (yalnız ilgili satırlar). Model yanıtları aynı gün gemini-3.5-flash-lite'ın
bu sayfalar için verdiği gerçek yanıtlardır (Actions dry-run 43798171255 vakaları).
"""

import fiyat_kontrol as fk
import pytest
from helpers import answer, plan


def targets(service_id, name, url, plans, student=()):
    cat = {
        "servisler": [{"id": service_id, "ad": name, "kategori": "video", "planlar": plans}],
        "operator_paketleri": [],
    }
    for p in cat["servisler"][0]["planlar"]:
        p["ogrenci"] = p["id"] in student
    return fk.collect_targets(cat)


def package_targets(pid, name, price, url):
    cat = {
        "servisler": [],
        "operator_paketleri": [
            {
                "id": pid,
                "operator": "Turkcell",
                "ad": name,
                "fiyat_tl": price,
                "periyot": "aylik",
                "icerir": [],
                "kaynak": url,
                "kontrol_tarihi": "2026-11-01",
                "dogrulandi": True,
                "izleme_url": url,
                "kaynak_notu": "12 ay taahhütlü",
            }
        ],
    }
    return fk.collect_targets(cat)


def by_key(findings):
    return {f.target.key: f for f in findings}


def decisions(findings):
    return {f.target.key: fk.decide(f) for f in findings}


# --------------------------------------------------------------------------
# Spotify: kart düzeni — ad fiyatın satır(lar) üstünde, öğrenci adı alıntıdan uzakta
# --------------------------------------------------------------------------

SPOTIFY_URL = "https://www.spotify.com/tr/premium/"
SPOTIFY_PAGE = "\n".join(
    [
        "Premium",
        "Bireysel",
        "İlk 1 ay boyunca ücretsiz",
        "Sonra ayda ₺115",
        "1 Premium hesabı",
        "İstediğin zaman iptal et",
        "Premium'u edin",
        "İlk 1 ay boyunca ücretsiz, sonra ayda ₺115. Sadece Premium'u daha önce denememiş kişiler "
        "tekliften yararlanabilir. Koşullar geçerlidir.",
        "İlk 1 ay boyunca ücretsiz",
        "Premium",
        "Öğrenci",
        "İlk 1 ay boyunca ücretsiz",
        "Sonra ayda ₺60",
        "Doğrulanmış 1 Premium hesabı",
        "Koşulları sağlayan öğrenciler için indirim",
        "İstediğin zaman iptal et",
        "Premium'u edin",
        "İlk 1 ay boyunca ücretsiz, sonra ayda ₺60. Teklif yalnızca koşulları karşılayan geçerli "
        "yükseköğretim kurumlarına kayıtlı olan öğrencilere özeldir. Premium'u daha önce deneyen "
        "kullanıcılar bu tekliften yararlanamaz. Spotify Öğrenci İndirimi Hüküm ve Koşulları'na tabidir.",
        "Premium",
        "Duo",
        "₺159 / ay",
        "2 Premium hesap",
        "İstediğin zaman iptal et",
        "Premium Duo planını edin",
        "Aynı adreste yaşayan çiftler için. Koşullar geçerlidir.",
        "Premium",
        "Aile",
        "₺199 / ay",
        "6 Premium hesabı",
    ]
)


def spotify_targets(duo=159, aile=199):
    return targets(
        "spotify",
        "Spotify Premium",
        SPOTIFY_URL,
        [
            plan("bireysel", "Premium Bireysel", 1, 115, SPOTIFY_URL),
            plan("ogrenci", "Premium Öğrenci", 1, 60, SPOTIFY_URL),
            plan("duo", "Premium Duo", 2, duo, SPOTIFY_URL),
            plan("aile", "Premium Aile", 3, aile, SPOTIFY_URL),
        ],
        student=("ogrenci",),
    )


def spotify_answers(**override):
    data = {
        "bireysel": answer("spotify/bireysel", 115, "İlk 1 ay boyunca ücretsiz, sonra ayda ₺115.", False, 1.0),
        "ogrenci": answer("spotify/ogrenci", 60, "İlk 1 ay boyunca ücretsiz, sonra ayda ₺60.", False, 1.0),
        "duo": answer("spotify/duo", 159, "₺159 / ay", False, 1.0),
        "aile": answer("spotify/aile", 199, "₺199 / ay", False, 1.0),
    }
    data.update(override)
    return {a["plan_id"]: a for a in data.values()}


def test_spotify_unchanged_card_prices_are_ok():
    findings = fk.validate_answers(spotify_targets(), spotify_answers(), SPOTIFY_PAGE)
    assert set(decisions(findings).values()) == {"ok"}, [(f.target.key, f.reasons) for f in findings]
    f = by_key(findings)
    # Bağlama sorunu güveni düşürmedi ama not olarak kaldı (dry-run özetinde görünür).
    assert any("ayrıca doğrulandı" in n for n in f["spotify/duo"].notes)
    assert any("ayrıca doğrulandı" in n for n in f["spotify/ogrenci"].notes)


def test_spotify_changed_duo_price_keeps_strict_binding():
    # Duo 159 → 179 olsun: alıntı yine adsız ("₺179 / ay") ve önündeki pencerede
    # "Öğrenci" var → bugünkü gibi PR değil, issue.
    page = SPOTIFY_PAGE.replace("₺159 / ay", "₺179 / ay")
    ans = spotify_answers(duo=answer("spotify/duo", 179, "₺179 / ay", True, 1.0))
    f = by_key(fk.validate_answers(spotify_targets(), ans, page))["spotify/duo"]
    assert f.changed and fk.decide(f) == "issue"
    assert any("birden çok plana" in r for r in f.reasons)


def test_unchanged_quote_borrowed_from_other_plan_is_not_confirmed():
    # Aile için Duo'nun fiyatı (159) bulunursa bu değişiklik sayılır → katı yol.
    ans = spotify_answers(aile=answer("spotify/aile", 159, "₺159 / ay", True, 1.0))
    f = by_key(fk.validate_answers(spotify_targets(), ans, SPOTIFY_PAGE))
    assert fk.decide(f["spotify/aile"]) == "issue"
    # Duo'nun fiyatını başka bir kayıt da bulduğu için (planlar arası kayma) Duo'nun
    # hafif onayı kapanır.
    assert fk.decide(f["spotify/duo"]) == "unconfirmed"
    assert f["spotify/duo"].confidence == 0.5


def test_same_catalog_price_in_group_blocks_unchanged_confirmation():
    # Duo ile Aile katalogda aynı fiyatta olsaydı adsız alıntı hangisine ait bilinemez.
    page = SPOTIFY_PAGE.replace("₺199 / ay", "₺159 / ay")
    ans = spotify_answers(aile=answer("spotify/aile", 159, "₺159 / ay", False, 1.0))
    findings = by_key(fk.validate_answers(spotify_targets(aile=159), ans, page))
    assert fk.decide(findings["spotify/duo"]) == "unconfirmed"
    assert fk.decide(findings["spotify/aile"]) == "unconfirmed"


# --------------------------------------------------------------------------
# iCloud+: tablo düzeni + üst simge dipnot rakamı (Türkiye³ → model "Türkiye3" yazıyor)
# --------------------------------------------------------------------------

ICLOUD_URL = "https://support.apple.com/tr-tr/108047"
ICLOUD_PAGE = "\n".join(
    [
        "iPhone, iPad, Mac veya PC'nizden iCloud+'a yükseltme yapabilirsiniz. Yükseltme işleminden sonra "
        "aylık olarak faturalandırılırsınız.1 Aşağıda ülkeye/bölgeye göre aylık fiyatlandırmayı ve "
        "planları görebilirsiniz.",
        "Ülke (Para Birimi)",
        "50 GB",
        "200 GB",
        "2 TB",
        "6 TB",
        "12 TB",
        "Tunus² (USD)",
        "$0.99",
        "$2.99",
        "$9.99",
        "$29.99",
        "$59.99",
        "Türkiye³ (TRY)",
        "49,99 TL",
        "169,99 TL",
        "549,99 TL",
        "1699,99 TL",
        "3399,99 TL",
        "Uganda²??³ (USD)",
        "$0.99",
        "$3.49",
    ]
)
ICLOUD_PLANS = [
    ("50gb", "50 GB", 49.99),
    ("200gb", "200 GB", 169.99),
    ("2tb", "2 TB", 549.99),
    ("6tb", "6 TB", 1699.99),
    ("12tb", "12 TB", 3399.99),
]
ICLOUD_PRICES = ["49,99 TL", "169,99 TL", "549,99 TL", "1699,99 TL", "3399,99 TL"]


def icloud_targets(**prices):
    plans = [plan(pid, ad, i, prices.get(f"p{pid}", fiyat), ICLOUD_URL) for i, (pid, ad, fiyat) in enumerate(ICLOUD_PLANS)]
    return targets("icloud-plus", "iCloud+", ICLOUD_URL, plans)


def icloud_answers(superscript="3"):
    out = {}
    for i, (pid, _, fiyat) in enumerate(ICLOUD_PLANS):
        quote = f"Türkiye{superscript} (TRY)\n" + "\n".join(ICLOUD_PRICES[: i + 1])
        out[f"icloud-plus/{pid}"] = answer(f"icloud-plus/{pid}", fiyat, quote, False, 1.0)
    return out


def test_compat_key_folds_superscript_digits():
    assert fk.quote_in_text_compat("Türkiye3 (TRY)\n49,99 TL", ICLOUD_PAGE)
    assert not fk.quote_in_text("Türkiye3 (TRY)\n49,99 TL", ICLOUD_PAGE)  # katı eşleşme değişmedi


@pytest.mark.parametrize("superscript", ["3", "³"])
def test_icloud_unchanged_table_prices_are_ok(superscript):
    findings = fk.validate_answers(icloud_targets(), icloud_answers(superscript), ICLOUD_PAGE)
    assert set(decisions(findings).values()) == {"ok"}, [(f.target.key, f.reasons) for f in findings]


def test_icloud_changed_price_with_superscript_mismatch_is_not_a_pr():
    # 200 GB 169,99 → 199,99: model yine "Türkiye3" yazarsa alıntı katı eşleşmez → issue.
    page = ICLOUD_PAGE.replace("169,99 TL", "199,99 TL")
    ans = icloud_answers()
    ans["icloud-plus/200gb"] = answer("icloud-plus/200gb", 199.99, "Türkiye3 (TRY)\n49,99 TL\n199,99 TL", True, 1.0)
    f = by_key(fk.validate_answers(icloud_targets(), ans, page))["icloud-plus/200gb"]
    assert fk.decide(f) == "issue"
    assert any("birebir bulunamadı" in r for r in f.reasons)


def test_icloud_changed_price_with_exact_quote_still_needs_binding():
    # Alıntı birebir olsa da tabloda plan adı alıntıya bağlanamıyor → bugünkü gibi issue.
    page = ICLOUD_PAGE.replace("169,99 TL", "199,99 TL")
    ans = icloud_answers("³")
    ans["icloud-plus/200gb"] = answer("icloud-plus/200gb", 199.99, "Türkiye³ (TRY)\n49,99 TL\n199,99 TL", True, 1.0)
    f = by_key(fk.validate_answers(icloud_targets(), ans, page))["icloud-plus/200gb"]
    assert fk.decide(f) == "issue"
    assert any("birden çok plana" in r or "adı geçmiyor" in r for r in f.reasons)
    assert not f.notes  # hafif onay yolu değişen fiyatta hiç denenmez


# --------------------------------------------------------------------------
# Disney+: kampanya kartları + dipnottaki normal fiyat + yıllık tablo
# --------------------------------------------------------------------------

DISNEY_URL = "https://www.disneyplus.com/tr-tr"
DISNEY_PAGE = "\n".join(
    [
        "*Teklif 24 Kasım 2026 tarihinde sona erecektir. Daha önce iptal etmediğiniz takdirde 2 ayın "
        "ardından üyeliğiniz o tarihte geçerli olan ilgili üyelik fiyatı (249,90 TL/ay tutarından "
        "başlayan fiyatlar) üzerinden devam eder.",
        "Üyeliğini seç",
        "24 Kasım’a kadar üye ol, aylık üyelikte 2 ay boyunca indirim fırsatından yararlan!",
        "Disney+ Reklamlı",
        "2 ay boyunca 169,90 TL / ay1",
        "Toplam 160,00 TL indirim",
        "Disney+ Reklamsız",
        "2 ay boyunca 299,90 TL / ay1",
        "Toplam 300,00 TL indirim",
        "SEÇ",
        "SEÇ",
        "Yıllık üyelik fiyatı",
        "2.499,00 TL / yıl",
        "4.499,00 TL / yıl",
        "4K UHD ve HDR kalitesine kadar video2",
    ]
)


def disney_targets():
    return targets(
        "disney-plus",
        "Disney+",
        DISNEY_URL,
        [
            plan("reklamli", "Reklamlı (aylık)", 1, 249.9, DISNEY_URL),
            plan("reklamli-yillik", "Reklamlı (yıllık)", 1, 2499, DISNEY_URL, periyot="yillik"),
            plan("reklamsiz-yillik", "Reklamsız (yıllık)", 2, 4499, DISNEY_URL, periyot="yillik"),
        ],
    )


def disney_answers(**override):
    data = {
        "reklamli": answer(
            "disney-plus/reklamli", 249.9, "249,90 TL/ay tutarından başlayan fiyatlar", False, 0.95
        ),
        "reklamli-yillik": answer(
            "disney-plus/reklamli-yillik", 2499.0, "2.499,00 TL / yıl", False, 0.95, "yillik"
        ),
        "reklamsiz-yillik": answer(
            "disney-plus/reklamsiz-yillik", 4499.0, "4.499,00 TL / yıl", False, 0.95, "yillik"
        ),
    }
    data.update(override)
    return {a["plan_id"]: a for a in data.values()}


def test_disney_unchanged_footnote_and_yearly_prices_are_ok():
    findings = fk.validate_answers(disney_targets(), disney_answers(), DISNEY_PAGE)
    assert set(decisions(findings).values()) == {"ok"}, [(f.target.key, f.reasons) for f in findings]


def test_disney_campaign_price_is_never_a_pr():
    ans = disney_answers(
        reklamli=answer("disney-plus/reklamli", 169.9, "2 ay boyunca 169,90 TL / ay1", True, 0.99)
    )
    f = by_key(fk.validate_answers(disney_targets(), ans, DISNEY_PAGE))["disney-plus/reklamli"]
    assert fk.decide(f) == "issue"
    assert any("kampanya" in r for r in f.reasons)


def test_yearly_price_written_as_monthly_elsewhere_blocks_confirmation():
    # Aynı fiyat sayfada başka bir periyotla da geçiyorsa (ör. "2.499,00 TL / ay") onay yok.
    page = DISNEY_PAGE + "\nKampanyasız aylık 2.499,00 TL / ay"
    f = by_key(fk.validate_answers(disney_targets(), disney_answers(), page))["disney-plus/reklamli-yillik"]
    assert fk.decide(f) == "unconfirmed"
    assert fk.price_periods_on_page(2499.0, page) == [{"yillik"}, {"aylik"}]


# --------------------------------------------------------------------------
# HBO Max: yıllık fiyat yalnız gizli plan seçici JSON'unda; ₺ ayrı alanda
# --------------------------------------------------------------------------

HBO_URL = "https://www.hbomax.com/tr/tr"
HBO_CARD = (
    '{{"id":"{id}","collectionTitle":"Yıllık","content":{{"planCard":{{"periodicityText":"Yıllık",'
    '"ctas":[{{"text":"Paket Seçin","code":"continue.account-creation.pre-purchase"}}],'
    '"productName":{{"richTextHtml":"<p>{name}</p>","plainText":"{name}"}},'
    '"price":{{"format":"{{{{currency}}}}{{{{amount}}}} / {{{{period}}}}","currencyCode":"TRY",'
    '"amount":{{"richTextHtml":"<p>{amount}</p>","plainText":"{amount}"}},'
    '"period":{{"richTextHtml":"<p>yıl</p>","plainText":"yıl"}},'
    '"currency":{{"richTextHtml":"<p>₺</p>","plainText":"₺"}}}},"pricePlan":{{"id":"{plan}"}}}}}}}}'
)


def hbo_html(standart="2.299,00", ozel="2.999,00"):
    cards = ",".join(
        [
            HBO_CARD.format(id="a5c3160a", name="Standart", amount=standart, plan="30359"),
            HBO_CARD.format(id="ff65ba04", name="Özel", amount=ozel, plan="30361"),
        ]
    )
    return (
        "<html><head><title>HBO Max</title></head><body>"
        "<div>AylıkYıllık</div><div>Standart</div><div>₺229,90 / ay</div>"
        "<div>Özel</div><div>₺299,90 / ay</div>"
        '<div class="plan-picker-source" data-plan-picker-source style="display:none">'
        '{"items":{"Yıllık":[' + cards + "]}}</div></body></html>"
    )


def hbo_targets():
    return targets(
        "hbo-max",
        "HBO Max",
        HBO_URL,
        [
            plan("standart", "Standart (aylık)", 1, 229.9, HBO_URL),
            plan("ozel", "Özel (aylık)", 2, 299.9, HBO_URL),
            plan("standart-yillik", "Standart (yıllık)", 1, 2299, HBO_URL, periyot="yillik"),
            plan("ozel-yillik", "Özel (yıllık)", 2, 2999, HBO_URL, periyot="yillik"),
        ],
    )


def hbo_answers(standart_yillik="Standart ₺2.299,00 / yıl", price=2299.0, changed=False):
    data = [
        answer("hbo-max/standart", 229.9, "Standart\n₺229,90 / ay", False, 1.0),
        answer("hbo-max/ozel", 299.9, "Özel\n₺299,90 / ay", False, 1.0),
        answer("hbo-max/standart-yillik", price, standart_yillik, changed, 1.0, "yillik"),
        answer("hbo-max/ozel-yillik", 2999.0, "Özel ₺2.999,00 / yıl", False, 1.0, "yillik"),
    ]
    return {a["plan_id"]: a for a in data}


def test_price_template_lines_render_hidden_plan_cards():
    assert fk.price_template_lines(hbo_html()) == ["Standart ₺2.299,00 / yıl", "Özel ₺2.999,00 / yıl"]


def test_price_template_card_without_name_does_not_borrow_previous_card_name():
    first = HBO_CARD.format(id="a", name="Standart", amount="2.299,00", plan="1")
    second = HBO_CARD.format(id="b", name="Özel", amount="2.999,00", plan="2").replace(
        '"productName":{"richTextHtml":"<p>Özel</p>","plainText":"Özel"},', ""
    )
    assert "productName" not in second
    assert fk.price_template_lines(first + "," + second) == [
        "Standart ₺2.299,00 / yıl",
        "₺2.999,00 / yıl",
    ]


def test_price_template_ignores_broken_or_incomplete_cards():
    assert fk.price_template_lines('"price":{"format":"{{currency}}{{amount}}","amount":') == []
    no_currency = '"price":{"format":"{{currency}}{{amount}}","amount":{"plainText":"9,99"}}'
    assert fk.price_template_lines(no_currency) == []


def test_extract_page_text_adds_card_section_without_duplicates():
    text = fk.extract_page_text(hbo_html())
    assert fk.PRICE_CARDS_HEADER in text
    cards = text.split(fk.PRICE_CARDS_HEADER, 1)[1]
    assert "Standart ₺2.299,00 / yıl" in cards and "Özel ₺2.999,00 / yıl" in cards
    # Görünür metinde zaten olan aylık kartlar tekrar eklenmez.
    assert "₺229,90" not in cards


def test_page_without_templates_is_unchanged():
    html = "<html><body><p>Bireysel ₺115/ay</p></body></html>"
    assert fk.PRICE_CARDS_HEADER not in fk.extract_page_text(html)


def test_hbo_yearly_prices_bind_strictly_from_rendered_cards():
    text = fk.extract_page_text(hbo_html())
    findings = fk.validate_answers(hbo_targets(), hbo_answers(), text)
    assert set(decisions(findings).values()) == {"ok"}
    assert by_key(findings)["hbo-max/standart-yillik"].notes == []  # hafif yola gerek kalmadı


def test_hbo_hallucinated_quote_stays_unconfirmed():
    # 2026-11-16 yanıtı: model sayfada olmayan "paşa yıl" yazdı.
    text = fk.extract_page_text(hbo_html())
    f = by_key(fk.validate_answers(hbo_targets(), hbo_answers("2.299,00\npaşa yıl"), text))
    assert fk.decide(f["hbo-max/standart-yillik"]) == "unconfirmed"


def test_hbo_yearly_increase_from_rendered_card_is_a_pr():
    text = fk.extract_page_text(hbo_html(standart="2.599,00"))
    ans = hbo_answers("Standart ₺2.599,00 / yıl", 2599.0, True)
    f = by_key(fk.validate_answers(hbo_targets(), ans, text))["hbo-max/standart-yillik"]
    assert fk.decide(f) == "pr", f.reasons


def test_prompt_states_catalog_price_unambiguously():
    prompt = fk.build_prompt(HBO_URL, hbo_targets(), "metin ₺1")
    assert "2.299 TL (yeni_fiyat_tl biçiminde 2299.00)" in prompt


# --------------------------------------------------------------------------
# Turkcell One: tek kayıtlı sayfa, taahhütlü + taahhütsüz iki fiyat
# --------------------------------------------------------------------------

ELITE_URL = "https://www.turkcell.com.tr/paket-ve-tarifeler/turkcell-one/turkcell-one-elite"
ELITE_PAGE = "\n".join(
    [
        "Turkcell One EliteTurkcell One Elite",
        "Servislerde Geçerli %42 İndirim",
        "Turkcell One Elite",
        "Turkcell One Elite ile tek bir yerden ve sabit fiyat garantisiyle favori platformlarınızın keyfini çıkarın!",
        "TAAHHÜTLÜ ABONELİK",
        "12 Fatura Dönemi",
        "990TL",
        "TAAHHÜTSÜZ ABONELİK",
        "1 Fatura Dönemi",
        "1.300TL",
        "Paket Detayları",
        "Katılım Kriterleri",
        "Tüm Turkcell bireysel faturalı ses hattı ve bireysel Superbox müşterileri yararlanabilir. "
        "Mobil ödemenin açık olması gerekmektedir.",
        "Diğer Satın Alma Seçenekleri",
        "Turkcell Uygulaması",
        "Turkcell Mağazaları",
        "532 ya da 0532 532 0000",
        "Ücretlendirme",
        "Taahhütlü Abonelik",
        "Taahhütsüz Abonelik",
        "Turkcell One Elite ile tek bir yerden favori platformlarınızın keyfini çıkarın!",
        "Paket ücreti 990 TL’dir.",
        "Üyelikte TV+ Premium X HBO Max, Amazon Prime, Netflix Premium, YouTube Premium, Wonjo Kids, "
        "Disney Reklamsız, Lifebox ve fizy sesli kitap yer alır.",
        "Turkcell One Elite ile tek bir yerden favori platformlarınızın keyfini çıkarın!",
        "Paket ücreti 1300 TL’dir.",
        "",
        "[Sayfa verisinde fiyat geçen parçalar]",
        "Servislerde Geçerli %42 İndirim #20cbfc #007ce0 POSTPAID TAAHHÜTLÜ ABONELİK 990 TL AY 1 12 Fatura Dönemi",
    ]
)


def elite():
    return package_targets("turkcell-one-elite", "Turkcell One Elite", 990, ELITE_URL)


@pytest.mark.parametrize(
    "quote",
    [
        "TAAHHÜTLÜ ABONELİK 990 TL AY 1 12 Fatura Dönemi",  # 2026-11-16 yanıtı (ad 150 karakterden uzakta)
        "TAAHHÜTLÜ ABONELİK\n12 Fatura Dönemi\n990TL",
        "Paket ücreti 990 TL’dir.",
    ],
)
def test_turkcell_unchanged_committed_price_is_ok(quote):
    (f,) = fk.validate_answers(elite(), {"paket/turkcell-one-elite": answer("paket/turkcell-one-elite", 990, quote, False, 1.0)}, ELITE_PAGE)
    assert fk.decide(f) == "ok", f.reasons


def test_turkcell_uncommitted_price_is_never_a_pr():
    # Model taahhütsüz fiyatı (1.300) yeni fiyat sanırsa: alıntıda ad olsa da PR değil.
    quote = "Turkcell One Elite ile tek bir yerden favori platformlarınızın keyfini çıkarın! Paket ücreti 1300 TL’dir."
    (f,) = fk.validate_answers(
        elite(), {"paket/turkcell-one-elite": answer("paket/turkcell-one-elite", 1300, quote, True, 1.0)}, ELITE_PAGE
    )
    assert f.changed and fk.decide(f) == "issue"
    assert any("taahhütsüz" in r for r in f.reasons)


def test_turkcell_committed_increase_is_still_a_pr():
    page = ELITE_PAGE.replace("990TL", "1.100TL").replace("990 TL", "1100 TL")
    quote = "Turkcell One Elite ile tek bir yerden favori platformlarınızın keyfini çıkarın! Paket ücreti 1100 TL’dir."
    (f,) = fk.validate_answers(
        elite(), {"paket/turkcell-one-elite": answer("paket/turkcell-one-elite", 1100, quote, True, 1.0)}, page
    )
    assert fk.decide(f) == "pr", f.reasons


def test_price_commitments():
    assert fk.price_commitments(990, ELITE_PAGE) == {"taahhutlu"}
    assert fk.price_commitments(1300, ELITE_PAGE) == {"taahhutsuz"}


@pytest.mark.parametrize("quote", ["TAAHHÜTSÜZ ABONELİK\n1 Fatura Dönemi\n1.300TL", "1.300TL"])
def test_unchanged_package_price_shown_only_as_uncommitted_is_not_confirmed(quote):
    # Katalog yanlışlıkla taahhütsüz fiyatı tutuyorsa ve ad alıntıya bağlanamıyorsa
    # hafif onay verilmez (ad sayfanın başında; kartlarla arasında uzun metin var).
    page = ELITE_PAGE.replace("TAAHHÜTLÜ ABONELİK\n", "Kampanya koşulları " * 12 + "\nTAAHHÜTLÜ ABONELİK\n", 1)
    targets_ = package_targets("turkcell-one-elite", "Turkcell One Elite", 1300, ELITE_URL)
    (f,) = fk.validate_answers(
        targets_, {"paket/turkcell-one-elite": answer("paket/turkcell-one-elite", 1300, quote, False, 1.0)}, page
    )
    assert fk.decide(f) == "unconfirmed"
    assert any("adı geçmiyor" in r for r in f.reasons)


# --------------------------------------------------------------------------
# Apple Music Öğrenci: "ekstra tasarruf" kalıcı öğrenci indirimi
# --------------------------------------------------------------------------

APPLE_URL = "https://www.apple.com/tr/apple-music/"
APPLE_PAGE = "\n".join(
    [
        "Bireysel",
        "Ayda sadece 89,99 TL.",
        "Yeni aboneler için ilk ay teklifi ile.*",
        "Öğrenci",
        "Ayda sadece",
        "49,99 TL ile ekstra tasarruf. Yeni aboneler için ilk ay teklifi ile.",
        "Aile",
        "Ayda sadece 149,99 TL.",
    ]
)
APPLE_Q = "Öğrenci\nAyda sadece\n49,99 TL ile ekstra tasarruf."


def apple_targets(ogrenci=49.99):
    return targets(
        "apple-music",
        "Apple Music",
        APPLE_URL,
        [
            plan("bireysel", "Bireysel", 1, 89.99, APPLE_URL),
            plan("ogrenci", "Öğrenci", 1, ogrenci, APPLE_URL),
            plan("aile", "Aile", 3, 149.99, APPLE_URL),
        ],
        student=("ogrenci",),
    )


def test_apple_music_student_savings_wording_is_ok_when_unchanged():
    ans = {"apple-music/ogrenci": answer("apple-music/ogrenci", 49.99, APPLE_Q, False, 1.0)}
    f = by_key(fk.validate_answers(apple_targets(), ans, APPLE_PAGE))["apple-music/ogrenci"]
    assert fk.decide(f) == "ok", f.reasons


def test_apple_music_student_savings_wording_still_blocks_a_change():
    ans = {"apple-music/ogrenci": answer("apple-music/ogrenci", 49.99, APPLE_Q, True, 1.0)}
    f = by_key(fk.validate_answers(apple_targets(ogrenci=39.99), ans, APPLE_PAGE))["apple-music/ogrenci"]
    assert fk.decide(f) == "issue"
    assert any("kampanya" in r for r in f.reasons)


def test_student_exception_does_not_cover_real_campaign_words():
    page = "Öğrenci\nİlk 3 ay 49,99 TL/ay"
    ans = {"apple-music/ogrenci": answer("apple-music/ogrenci", 49.99, "İlk 3 ay 49,99 TL/ay", False, 1.0)}
    f = by_key(fk.validate_answers(apple_targets(), ans, page))["apple-music/ogrenci"]
    assert fk.decide(f) == "unconfirmed"


# --------------------------------------------------------------------------
# Özet: nedenler dry-run çıktısında görünür
# --------------------------------------------------------------------------


def test_summary_rows_show_reasons():
    summary = {
        "tarih": "2026-11-16",
        "mod": "actions",
        "model": "m",
        "hata": 0,
        "pr": "",
        "acilan_issue": [],
        "guncellenen_issue": [],
        "zaten_acik_issue": [],
        "bastirilan_tespitler": [],
        "basarisiz_islemler": [],
        "kaynaklar": [
            {
                "url": "https://x",
                "durum": "ok",
                "ayrinti": "",
                "metin_uzunlugu": 10,
                "fiyat_ornekleri": [],
                "kararlar": [
                    {"kayit": "a/b", "karar": "unconfirmed", "guven": 0.5, "fiyat": 1.0, "nedenler": ["Neden X."]},
                    {"kayit": "a/c", "karar": "ok", "guven": 1.0, "fiyat": 2.0, "nedenler": []},
                ],
            }
        ],
    }
    out = fk.render_summary(summary)
    assert "unconfirmed (Neden X.)" in out
    assert "| ok | güven 1.0" in out
