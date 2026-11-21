# borsamorsa.com nöbetçisi

[borsamorsa.com](https://borsamorsa.com) için KAP (Kamuyu Aydınlatma Platformu) bildirim listesini 10 dakikada bir yoklayan küçük bir görev.

- KAP'ın herkese açık bildirim listesine çalıştırma başına tek istek gönderir.
- Sitede izlenen şirketlerin finansal rapor, kâr payı, yeni iş ilişkisi, pay geri alımı ve sermaye artırımı bildirimlerini ayırır.
- İlk kez gördüğü her bildirimi görülme saatiyle `durum/gorulen.json` dosyasına yazar.

Şu an **kuru çalışma**: yalnız kayıt tutar; hiçbir şeyi yayınlamaz ve başka bir işi başlatmaz.

## Kapatma anahtarı

`ayar.json` içinde `"acik": false` yapılırsa KAP'a hiç istek gitmez. (Mac'te toplu KAP taraması yapılacaksa önce kapatılır, bitince açılır.)

## Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `nobetci.py` | Yoklama betiği |
| `ayar.json` | Açık/kapalı, kuru çalışma, izlenen türler |
| `kodlar.json` | İzlenen şirket kodları (günde bir siteden yenilenir) |
| `durum/gorulen.json` | Görülen bildirimler ve görülme saatleri |
| `ham/geri_alim/` | Pay geri alım bildirimlerinin KAP'taki sayfaları (son 60 gün) |

Bu depoda anahtar, parola ya da kişisel veri bulunmaz.
