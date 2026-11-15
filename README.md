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

## Otomasyon (günlük fiyat kontrolü)
`.github/workflows/fiyat-kontrol.yml` her gün **09:00 (TR)** çalışır; elle de başlatılabilir (Actions → Fiyat kontrol → Run workflow; `dry_run` ile hiçbir şey yazmadan dener).

- `scripts/fiyat_kontrol.py`, `izleme_url`'si olan her fiyat sayfasını indirir ve sayfadaki fiyatları Gemini'ye karşılaştırtır. Modelin verdiği kanıt alıntısı sayfada birebir geçmiyorsa sonuç "emin değil" sayılır.
- **Pull request (PR) = onay bekleyen fiyat değişikliği.** Bot fiyatın değiştiğinden eminse `fiyat/guncelleme` dalında PR açar (açık PR varsa ona ekler): eski → yeni fiyat, % değişim, kanıt alıntısı ve kaynak linkiyle. PR **birleştirilmeden hiçbir fiyat yayınlanmaz**. Fiyat düştüyse ya da %200'den fazla arttıysa PR "olağandışı" etiketi alır.
- **Issue = elle bakılması gereken durum.** Bot emin değilse, kayıt tahminiyse (`dogrulandi: false`), sayfa 3 gün üst üste okunamazsa, şema doğrulaması geçmezse ya da Gemini'ye ulaşılamayıp sayfadaki fiyatlar değiştiyse issue açar. Aynı başlıkta açık issue varsa yenisini açmaz.
- Haftalık (pazartesi): izlenemeyen kayıtların özeti, `iptal-rehberleri.json` link kontrolü, 7 günden eski açık fiyat PR'ı için hatırlatma ve `durum/son-calisma.json` sağlık kaydı.
- Bot doğrudan `main`'e yalnızca `durum/` klasörüne yazar (fiyat içermez).
- Yerelde deneme: `pip install -r requirements.txt`, `python -m pytest`, `python scripts/fiyat_kontrol.py --dry-run` (anahtar yoksa yalnızca sayfa indirme ve metin çıkarma raporlanır).
- Gerekenler: depo sırrı `GEMINI_API_KEY`; isteğe bağlı depo değişkeni `GEMINI_MODEL`; Settings → Actions → "Allow GitHub Actions to create and approve pull requests" açık.
- Bot yanlış bir tespit yaptıysa PR'ı ya da issue'yu **`yanlis-tespit` etiketiyle kapat**: aynı plan + aynı fiyat 30 gün boyunca yeniden bildirilmez.
- **Netflix ve YouTube yerelden izlenir** (`scripts/yerel_kaynaklar.json`): bu sayfalar fiyatı IP'ye göre gösterdiği için Actions onları atlar; Türkiye'deki bir Windows bilgisayarda Görev Zamanlayıcı her gün 10:00'da `fiyat_kontrol.py --yerel` çalıştırır (kendi `durum/yerel-*.json` dosyaları, aynı PR/issue akışı). Yerel koşu 3 gündür çalışmadıysa (ya da hiç kurulmadıysa) Actions koşusu issue açar.
- Kurulum (ayrı klon `%USERPROFILE%\IptalBey\veri-yerel`, `.venv`, görev): `powershell -ExecutionPolicy Bypass -File scripts\yerel_kurulum.ps1 -GitName <ad> -GitEmail <noreply-adresi> -Kaydet`. Kaldırma: aynı betik `-Kaldir`. Gerekenler: `gh auth login`, `setx GEMINI_API_KEY "<anahtar>"`. Günlükler: `%USERPROFILE%\IptalBey\loglar`.
