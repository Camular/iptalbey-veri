"""'N Aylık' süre ifadesi (F2.38 canlı koşu, Actions 45974489134).

PlayStation Plus sayfası yıllık fiyatı "12 Aylık Abonelik SkuPrice 2.890,00 TL" diye
yazar; bot "Aylık" sözcüğünü aylık periyot sayıp üç yıllık planı 'unconfirmed'
bırakıyordu. 12 ay yıllıktır; 3/6 ay ne aylık ne yıllıktır; 1 ay aylıktır.
Sayfa satırları 2026-11-27'de `extract_page_text` ile alınan metinden kısaltıldı.
"""

import fiyat_kontrol as fk
import pytest
from helpers import answer, plan

URL = "https://www.playstation.com/tr-tr/ps-plus/"
PAGE = "\n".join(
    [
        "Product PlayStation Plus Extra: 1 Aylık Abonelik SkuPrice 600,00 TL",
        "Product PlayStation Plus Extra: 3 Aylık Abonelik SkuPrice 1.620,00 TL",
        "Product PlayStation Plus Essential: 12 Aylık Abonelik SkuPrice 2.890,00 TL",
        "Product PlayStation Plus Extra: 12 Aylık Abonelik SkuPrice 4.810,00 TL",
        "Product PlayStation Plus Deluxe: 12 Aylık Abonelik SkuPrice 5.560,00 TL",
    ]
)


def periods_of(quote, price):
    norm = fk.normalize_text(quote)
    return fk.quote_context(norm, fk.find_price_match(price, norm)).periods


@pytest.mark.parametrize(
    ("quote", "price", "expected"),
    [
        ("PlayStation Plus Essential: 12 Aylık Abonelik SkuPrice 2.890,00 TL", 2890.0, {"yillik"}),
        ("12 aylık üyelik 4.810,00 TL", 4810.0, {"yillik"}),
        ("PlayStation Plus Extra: 1 Aylık Abonelik SkuPrice 600,00 TL", 600.0, {"aylik"}),
        ("PlayStation Plus Extra: 3 Aylık Abonelik SkuPrice 1.620,00 TL", 1620.0, {"coklu_ay"}),
        ("6 aylık paket 900,00 TL", 900.0, {"coklu_ay"}),
    ],
)
def test_n_month_wording_maps_to_its_real_period(quote, price, expected):
    assert periods_of(quote, price) == expected


def test_price_periods_on_page_reads_12_months_as_yearly():
    assert fk.price_periods_on_page(2890.0, PAGE) == [{"yillik"}]
    assert fk.price_periods_on_page(1620.0, PAGE) == [{"coklu_ay"}]


def ps_targets():
    cat = {
        "servisler": [
            {
                "id": "playstation-plus",
                "ad": "PlayStation Plus",
                "kategori": "oyun",
                "planlar": [
                    plan("extra", "Extra", 2, 600, URL),
                    plan("essential-yillik", "Essential (12 ay)", 1, 2890, URL, periyot="yillik"),
                    plan("extra-yillik", "Extra (12 ay)", 2, 4810, URL, periyot="yillik"),
                    plan("deluxe-yillik", "Deluxe (12 ay)", 3, 5560, URL, periyot="yillik"),
                ],
            }
        ],
        "operator_paketleri": [],
    }
    return fk.collect_targets(cat)


def ps_answers(**override):
    data = {
        "extra": answer(
            "playstation-plus/extra", 600.0, "PlayStation Plus Extra: 1 Aylık Abonelik SkuPrice 600,00 TL", False
        ),
        "essential-yillik": answer(
            "playstation-plus/essential-yillik",
            2890.0,
            "PlayStation Plus Essential: 12 Aylık Abonelik SkuPrice 2.890,00 TL",
            False,
            0.95,
            "yillik",
        ),
        "extra-yillik": answer(
            "playstation-plus/extra-yillik",
            4810.0,
            "PlayStation Plus Extra: 12 Aylık Abonelik SkuPrice 4.810,00 TL",
            False,
            0.95,
            "yillik",
        ),
        "deluxe-yillik": answer(
            "playstation-plus/deluxe-yillik",
            5560.0,
            "PlayStation Plus Deluxe: 12 Aylık Abonelik SkuPrice 5.560,00 TL",
            False,
            0.95,
            "yillik",
        ),
    }
    data.update(override)
    return {a["plan_id"]: a for a in data.values()}


def test_ps_plus_unchanged_12_month_prices_are_ok():
    findings = fk.validate_answers(ps_targets(), ps_answers(), PAGE)
    got = {f.target.key: (fk.decide(f), f.reasons) for f in findings}
    assert {k: d for k, (d, _) in got.items()} == {
        "playstation-plus/extra": "ok",
        "playstation-plus/essential-yillik": "ok",
        "playstation-plus/extra-yillik": "ok",
        "playstation-plus/deluxe-yillik": "ok",
    }, got


def test_3_month_price_is_never_bound_to_a_monthly_plan():
    ans = ps_answers(
        extra=answer(
            "playstation-plus/extra", 1620.0, "PlayStation Plus Extra: 3 Aylık Abonelik SkuPrice 1.620,00 TL", True
        )
    )
    findings = {f.target.key: f for f in fk.validate_answers(ps_targets(), ans, PAGE)}
    assert fk.decide(findings["playstation-plus/extra"]) != "pr"
