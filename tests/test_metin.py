"""Sayfa metni çıkarma ve alıntı/fiyat eşleştirme testleri."""

import json

import fiyat_kontrol as fk

WORD_JOINER = chr(0x2060)
BACKSLASH = chr(92)


def test_visible_text_inline_tags_stay_on_one_line():
    html = (
        "<html><head><style>.a{color:red}</style></head><body><ul>"
        '<li><span class="b">Temel plan</span>: Ayda 259,99 TL</li>'
        '<li><span class="b">Premium plan</span>: Ayda 499,99 TL</li>'
        "</ul></body></html>"
    )
    text = fk.extract_page_text(html)
    assert "Temel plan: Ayda 259,99 TL" in text
    assert "Premium plan: Ayda 499,99 TL" in text
    assert "color:red" not in text


def test_embedded_json_price_is_captured_from_script():
    data = {
        "subtitle": {
            "runs": [
                {"text": "İlk ay ₺0"},
                {"text": " • Ardından "},
                {"text": f"₺119,99{WORD_JOINER}/{WORD_JOINER}ay"},
            ]
        },
        "trackingParams": "CEcQ040EIhMI6KrRnM2JmAMVQHt6BR1-BhNC",
        "style": "BUTTON_VIEW_MODEL_STYLE_CTA",
    }
    html = (
        "<html><body><div>YouTube Premium</div>"
        f"<script>var ytInitialData = {json.dumps(data, ensure_ascii=False)};</script>"
        "</body></html>"
    )
    text = fk.extract_page_text(html)
    assert "Ardından ₺119,99/ay" in text
    assert "CEcQ040EIhMI6KrRnM2JmAMVQHt6BR1" not in text  # kimlik gürültüsü atılır
    assert "BUTTON_VIEW_MODEL_STYLE_CTA" not in text
    assert fk.has_price(text)


def test_escaped_lira_sign_in_script_is_decoded():
    escaped = BACKSLASH + "u20ba"
    html = f'<html><body><script>window.d={{"price":"Aylık {escaped}60"}}</script></body></html>'
    text = fk.extract_page_text(html)
    assert "Aylık ₺60" in text


def test_country_code_tl_is_not_a_price():
    html = (
        "<html><body><p>Yardım merkezi</p>"
        '<script>var c=[{"value":"TL","label":"Timor-Leste"}];</script></body></html>'
    )
    text = fk.extract_page_text(html)
    assert not fk.has_price(text)


def test_text_is_limited_and_keeps_prices():
    filler = "<p>" + "lorem ipsum dolor sit amet " * 40 + "</p>"
    html = "<html><body>" + filler * 60 + "<p>Bireysel: ayda 115 TL</p>" + filler * 60 + "</body></html>"
    text = fk.extract_page_text(html, max_chars=30_000)
    assert len(text) <= 30_000
    assert "Bireysel: ayda 115 TL" in text


def test_price_fingerprint_ignores_non_price_changes():
    a = "Oturum abc123 Bireysel ₺115 Aile ₺199"
    b = "Oturum zzz999 Bireysel ₺115 Aile ₺199"
    c = "Oturum abc123 Bireysel ₺129 Aile ₺199"
    assert fk.price_fingerprint(a) == fk.price_fingerprint(b)
    assert fk.price_fingerprint(a) != fk.price_fingerprint(c)


def test_quote_matching_ignores_whitespace_and_case():
    page = "Aylık planlar\nBireysel İlk ay ₺0 • Ardından ₺119,99/ay"
    assert fk.quote_in_text("bireysel  İlk ay ₺0 • ardından ₺119,99 /ay", page)
    assert fk.quote_in_text("Ardından ₺119,99/ay", page)
    assert not fk.quote_in_text("Ardından ₺129,99/ay", page)
    assert not fk.quote_in_text("", page)


def test_number_candidates_turkish_and_english_formats():
    assert fk.number_candidates("1.199,99") == {1199.99}
    assert fk.number_candidates("1,199.99") == {1199.99}
    assert fk.number_candidates("119,99") == {119.99}
    assert fk.number_candidates("329.99") == {329.99}
    assert fk.number_candidates("1.199") == {1.199, 1199.0}
    assert fk.number_candidates("115") == {115.0}


def test_price_in_quote():
    assert fk.price_in_quote(119.99, "İlk ay ₺0 • Ardından ₺119,99/ay")
    assert fk.price_in_quote(1199.99, "12 ay boyunca ₺1.199,99")
    assert fk.price_in_quote(115.0, "Sonra ayda ₺115.")
    assert not fk.price_in_quote(129.99, "Ardından ₺119,99/ay")
