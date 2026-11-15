"""Katalog dosyalarını şemaya ve referans bütünlüğüne göre doğrular.

Kullanım: python scripts/sema_dogrula.py [--fiyatlar YOL] [--rehberler YOL]
Hata varsa okunur liste basar ve 1 ile çıkar.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fiyat_kontrol import validate_catalog

KOK = Path(__file__).resolve().parent.parent


def _yukle(yol: Path) -> tuple[object | None, str | None]:
    try:
        return json.loads(yol.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"{yol.name}: dosya okunamadı ({e})"
    except json.JSONDecodeError as e:
        return None, f"{yol.name}: geçersiz JSON ({e})"


def tekrarlar(katalog: dict) -> list[str]:
    hatalar: list[str] = []
    servisler = [s for s in katalog.get("servisler", []) if isinstance(s, dict)]
    for sid, n in Counter(s.get("id") for s in servisler).items():
        if n > 1:
            hatalar.append(f"servis id'si tekrarlı: '{sid}' ({n} kez)")
    for s in servisler:
        planlar = [p for p in s.get("planlar", []) if isinstance(p, dict)]
        for pid, n in Counter(p.get("id") for p in planlar).items():
            if n > 1:
                hatalar.append(f"{s.get('id')}: plan id'si tekrarlı: '{pid}' ({n} kez)")
    return hatalar


def rehber_referanslari(katalog: dict, rehberler: dict) -> list[str]:
    ids = {s.get("id") for s in katalog.get("servisler", []) if isinstance(s, dict)}
    return [
        f"iptal rehberi '{r.get('id', '?')}': katalogda olmayan servis '{r.get('servis')}'"
        for r in rehberler.get("rehberler", [])
        if isinstance(r, dict) and r.get("servis") not in ids
    ]


def dogrula(fiyatlar: Path, rehberler: Path, sema_dizini: Path) -> list[str]:
    hatalar: list[str] = []
    katalog, e1 = _yukle(fiyatlar)
    rehber, e2 = _yukle(rehberler)
    fs, e3 = _yukle(sema_dizini / "fiyatlar.schema.json")
    rs, e4 = _yukle(sema_dizini / "iptal-rehberleri.schema.json")
    hatalar += [e for e in (e1, e2, e3, e4) if e]
    if hatalar:
        return hatalar
    if isinstance(katalog, dict):
        hatalar += [f"{fiyatlar.name}: {m}" for m in validate_catalog(katalog, fs)]
        hatalar += [f"{fiyatlar.name}: {m}" for m in tekrarlar(katalog)]
    else:
        hatalar.append(f"{fiyatlar.name}: kök nesne olmalı")
    if isinstance(rehber, dict):
        v = jsonschema.Draft202012Validator(rs)
        for e in sorted(v.iter_errors(rehber), key=lambda e: list(e.absolute_path)):
            yol = "/".join(str(p) for p in e.absolute_path) or "(kök)"
            hatalar.append(f"{rehberler.name}: {yol}: {e.message}")
        if isinstance(katalog, dict):
            hatalar += [f"{rehberler.name}: {m}" for m in rehber_referanslari(katalog, rehber)]
    else:
        hatalar.append(f"{rehberler.name}: kök nesne olmalı")
    return hatalar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fiyatlar", type=Path, default=KOK / "fiyatlar.json")
    ap.add_argument("--rehberler", type=Path, default=KOK / "iptal-rehberleri.json")
    ap.add_argument("--sema-dizini", type=Path, default=KOK / "sema")
    a = ap.parse_args(argv)
    hatalar = dogrula(a.fiyatlar, a.rehberler, a.sema_dizini)
    if hatalar:
        print(f"Doğrulama BAŞARISIZ ({len(hatalar)} hata):")
        for h in hatalar:
            print(f"  - {h}")
        return 1
    print("Doğrulama başarılı: hata yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
