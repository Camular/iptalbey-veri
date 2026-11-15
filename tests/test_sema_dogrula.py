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
