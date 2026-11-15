# iptalbey-veri

İptalBey uygulamasının herkese açık veri deposu. Uygulama yalnızca bu depodaki iki dosyayı okur:

| Dosya | İçerik | Ham adres |
|---|---|---|
| `fiyatlar.json` | Türkiye'deki dijital abonelik fiyatları ve operatör paketleri | https://raw.githubusercontent.com/Camular/iptalbey-veri/main/fiyatlar.json |
| `iptal-rehberleri.json` | Servis bazında iptal adımları | https://raw.githubusercontent.com/Camular/iptalbey-veri/main/iptal-rehberleri.json |

Şemalar `sema/` klasöründe (JSON Schema 2020-12).

## Kurallar
- Her fiyatın bir `kaynak` adresi ve `kontrol_tarihi` vardır. Resmi kaynaktan doğrulanamayan fiyatlar `dogrulandi: false` olarak tutulur ve uygulamada "tahmini" etiketiyle gösterilir.
- Fiyat değişiklikleri otomatik hazırlanır ama **yalnızca insan onayıyla (pull request birleştirilerek)** yayınlanır.
- Mağaza sitelerinden veri kazınmaz; yalnızca servislerin kendi fiyat sayfaları ve güvenilir haber kaynakları kullanılır.

## Hata bildirimi
Yanlış veya eski bir fiyat gördüyseniz bu depoda bir issue açın; kaynağı (bağlantı) eklemeniz yeterli.

`docs/` klasörü GitHub Pages ile yayınlanır (gizlilik politikası).
