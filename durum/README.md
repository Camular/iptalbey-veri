# durum/

Fiyat kontrol otomasyonunun kendi kayıtları. **Fiyat içermez**, uygulama okumaz. Botun onaysız commit atabildiği tek klasör budur.

| Dosya | İçerik |
|---|---|
| `son-calisma.json` | Haftalık sağlık kaydı (heartbeat): tarih, kontrol edilen kaynak sayısı, hata sayısı, kullanılan model |
| `okuma-hatalari.json` | Kaynak (URL) ve kayıt başına ardışık hata günü sayacı; 3. günde issue açılır |
| `sayfa-ozetleri.json` | Her fiyat sayfasındaki fiyat ifadelerinin karması (Gemini erişilemezse "sayfa değişti" yedek kontrolü) |
