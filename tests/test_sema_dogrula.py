import copy
import json

import sema_dogrula as sd
from helpers import catalog


def yaz(tmp_path, kat, rehber=None):
    f = tmp_path / "fiyatlar.json"
    r = tmp_path / "iptal-rehberleri.json"
    f.write_text(json.dumps(kat), encoding="utf-8")
    r.write_text(
        json.dumps(rehber or {"sema_surumu": 1, "surum": 1, "guncelleme": "2026-11-01", "rehberler": []}),
        encoding="utf-8",
    )
    return ["--fiyatlar", str(f), "--rehberler", str(r)]


def test_gecerli_katalog(tmp_path):
    assert sd.main(yaz(tmp_path, catalog())) == 0


def test_gercek_dosyalar():
    assert sd.main([]) == 0


def test_sema_hatasi(tmp_path, capsys):
    k = catalog()
    del k["servisler"][0]["ad"]
    assert sd.main(yaz(tmp_path, k)) == 1
    assert "BAŞARISIZ" in capsys.readouterr().out


def test_bozuk_referans(tmp_path, capsys):
    k = catalog()
    k["operator_paketleri"] = [
        {"id": "x", "icerir": [{"servis": "yok", "plan": None}]}
    ]
    assert sd.main(yaz(tmp_path, k)) == 1
    assert "yok" in capsys.readouterr().out


def test_rehber_bilinmeyen_servis():
    k = catalog()
    h = sd.rehber_referanslari(k, {"rehberler": [{"id": "g", "servis": "yok"}]})
    assert len(h) == 1


def test_tekrarli_id(tmp_path, capsys):
    k = catalog()
    k["servisler"].append(copy.deepcopy(k["servisler"][0]))
    assert sd.main(yaz(tmp_path, k)) == 1
    assert "tekrarlı" in capsys.readouterr().out


def test_tekrarli_plan_id():
    k = catalog()
    k["servisler"][0]["planlar"].append(copy.deepcopy(k["servisler"][0]["planlar"][0]))
    assert any("plan id" in h for h in sd.tekrarlar(k))


# --- Şema 2: yalnız tanınan servisler (KR-055, F2.36) ---


def taninan(**ek):
    kayit = {
        "id": "deezer-test",
        "ad": "Deezer",
        "kategori": "muzik",
        "hesap_url": "https://www.deezer.com/tr/account",
        "kontrol_tarihi": "2026-11-25",
    }
    kayit.update(ek)
    return kayit


def test_taninan_servis_gecerli(tmp_path):
    k = catalog()
    k["taninan_servisler"] = [taninan(), taninan(id="mubi", ad="MUBI", hesap_url=None, kategori="video")]
    assert sd.main(yaz(tmp_path, k)) == 0


def test_taninan_hesap_url_istege_bagli(tmp_path):
    k = catalog()
    kayit = taninan()
    del kayit["hesap_url"]
    k["taninan_servisler"] = [kayit]
    assert sd.main(yaz(tmp_path, k)) == 0


def test_taninan_fiyat_alani_reddedilir(tmp_path, capsys):
    for alan, deger in (("fiyat_tl", 99), ("planlar", []), ("fiyat", 10), ("periyot", "aylik")):
        k = catalog()
        k["taninan_servisler"] = [taninan(**{alan: deger})]
        assert sd.main(yaz(tmp_path, k)) == 1, alan
        assert "BAŞARISIZ" in capsys.readouterr().out


def test_taninan_zorunlu_alan_ve_kategori(tmp_path):
    k = catalog()
    k["taninan_servisler"] = [taninan(kategori="bilinmeyen")]
    assert sd.main(yaz(tmp_path, k)) == 1
    k["taninan_servisler"] = [{"id": "x", "ad": "X", "kategori": "diger"}]  # kontrol_tarihi yok
    assert sd.main(yaz(tmp_path, k)) == 1


def test_taninan_url_https_olmali(tmp_path):
    k = catalog()
    k["taninan_servisler"] = [taninan(hesap_url="http://example.com")]
    assert sd.main(yaz(tmp_path, k)) == 1


def test_taninan_id_fiyatli_servisle_cakisamaz(tmp_path, capsys):
    k = catalog()
    k["taninan_servisler"] = [taninan(id="spotify")]
    assert sd.main(yaz(tmp_path, k)) == 1
    assert "tekrarlı" in capsys.readouterr().out


def test_taninan_taninan_id_tekrari():
    k = catalog()
    k["taninan_servisler"] = [taninan(), taninan()]
    assert any("tekrarlı" in h for h in sd.tekrarlar(k))


def test_sema_1_reddedilir(tmp_path):
    k = catalog()
    k["sema_surumu"] = 1
    assert sd.main(yaz(tmp_path, k)) == 1


def test_taninan_servis_rehbere_baglanabilir():
    k = catalog()
    k["taninan_servisler"] = [taninan()]
    assert sd.rehber_referanslari(k, {"rehberler": [{"id": "g", "servis": "deezer-test"}]}) == []
