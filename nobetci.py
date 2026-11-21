#!/usr/bin/env python3
"""borsamorsa.com nöbetçisi — KAP bildirim listesini 10 dakikada bir yoklar.

Ne yapar: KAP'ın herkese açık bildirim listesinden son 3 günü sorar (tek istek), borsamorsa.com'da izlenen şirketlerin
finansal rapor, kâr payı, yeni iş ilişkisi, pay geri alımı ve sermaye artırımı bildirimlerini ayırır ve ilk kez gördüğü her bildirimi görülme saatiyle
durum/gorulen.json dosyasına yazar.

Şimdilik KURU ÇALIŞMA: yalnız kayıt tutar; hiçbir şeyi yayınlamaz, başka bir işi başlatmaz (ayar.json "kuru": true).
Ek olarak pay geri alım bildirimlerinin sayfalarını ham/geri_alim/ altına indirir (ayar.json "sayfa"); ana depo günlük
taramasında bu dosyaları okur. Çalıştırma başına en çok 8 sayfa, 10 saniye arayla.
Amaç, nöbetçinin her bildirimi zamanında ve doğru gördüğünü günlük taramalarla karşılaştırarak kanıtlamak.

Kapatma anahtarı: ayar.json içinde "acik": false → KAP'a hiç istek gitmez.
KAP'a yük: çalıştırma başına 1 liste isteği (liste 2000 kayda dayanırsa gün gün, en çok 3 istek) + en çok 8 sayfa isteği.

Kullanım: python3 nobetci.py            çıkış 0 (yeni bildirim olsa da olmasa da) · 1 KAP yanıt vermedi ya da liste güvenilmez
"""
import datetime, gzip, json, os, re, sys, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

KOK = os.path.dirname(os.path.abspath(__file__))
AYAR = os.path.join(KOK, "ayar.json")
KODLAR = os.path.join(KOK, "kodlar.json")
GORULEN = os.path.join(KOK, "durum", "gorulen.json")
KAP = "https://kap.org.tr/tr/api/disclosure/members/byCriteria"
SIRKETLER = "https://borsamorsa.com/data/sirketler.json"
SAYFA = "https://www.kap.org.tr/tr/api/notification/export/excel/"   # bildirim sayfası (ana depodaki taramalarla aynı adres)
HAM = os.path.join(KOK, "ham")
# Sayfası da indirilen türler: tür → (dosya öneki, sayfada bulunması gereken metin). Ana depo bu dosyaları okur; burada
# indirmek ana deponun sınırlı Actions dakikasını harcamaz. Bildirim biçiminde olmayan (bakım/hata) sayfa kaydedilmez.
SAYFA_TUR = {"geri_alim": ("GE_", "Yönetim Kurulu Karar Tarihi".encode("utf-8"))}
SAYFA_EN_COK = 8      # çalıştırma başına en çok sayfa (10 dakikada bir çalışır; gün boyu yayılır, KAP'a yük bindirmez)
SAYFA_ARA = 10        # iki sayfa isteği arası bekleme (sn)
SAYFA_DENEME = 6      # bir sayfa bu kadar turda alınamazsa bırakılır (günlükte uyarı)
SAYFA_ZAMAN = 20      # tek sayfa isteğinde en çok bekleme (sn)
SAYFA_BUTCE = 240     # bir turda sayfa indirmeye ayrılan toplam süre (sn); iş 8 dakikada kesilir
UA = "Mozilla/5.0 (compatible; borsamorsa/1.0; +https://borsamorsa.com/hakkinda/)"
IST = ZoneInfo("Europe/Istanbul")
SINIR = 2000          # KAP tek sorguda en çok bu kadar kayıt döndürür
GUN = 3               # son kaç günün listesi (gece yarısını ve gecikmiş çalıştırmaları kapsar)
SAKLA_GUN = 60        # kayıtlar bu kadar gün tutulur
ARA = 5               # iki KAP isteği arası bekleme (sn)
TURLER = {
    "Finansal Rapor": "bilanco",
    "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim": "temettu",
    "Kar Payı Avansı Ödemesi İşlemlerine İlişkin Bildirim": "temettu",
    "Yeni İş İlişkisi": "yeni_is",
    "Payların Geri Alınmasına İlişkin Bildirim": "geri_alim",
}
# Sermaye artırımı bildirimlerinin başlığı tek değil; ana depodaki kap_temettu.SERMAYE_RE ile aynı desen
SERMAYE_RE = re.compile(r"sermaye artırım|sermaye azaltım|bedelsiz|bedelli|rüçhan|pay mali hak kullanım|kayıtlı sermaye tavan|pay bölünme", re.I)
TUM_TURLER = sorted(set(TURLER.values()) | {"sermaye"})


def tur_bul(konu):
    """Bildirim başlığı → iş türü ya da None."""
    konu = (konu or "").strip()
    return TURLER.get(konu) or ("sermaye" if SERMAYE_RE.search(konu) else None)


def simdi():
    return datetime.datetime.now(IST)


def oku(yol, yoksa):
    try:
        with open(yol, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return yoksa


def yaz(yol, veri):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = yol + ".yeni"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write("\n")
    os.replace(gecici, yol)


def kap_liste(bas, son):
    """[bas, son] aralığındaki bütün bildirimler (piyasa geneli). 429'da bir kez 90 sn bekler."""
    govde = json.dumps({"fromDate": bas.isoformat(), "toDate": son.isoformat(), "mkkMemberOidList": []}).encode()
    basliklar = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "tr",
                 "Origin": "https://kap.org.tr", "Referer": "https://kap.org.tr/tr/", "Content-Type": "application/json"}
    for deneme in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(KAP, data=govde, headers=basliklar), timeout=60) as r:
                L = json.loads(r.read().decode("utf-8"))
            if not isinstance(L, list):
                raise ValueError("liste beklenirken başka bir yanıt geldi")
            return L
        except urllib.error.HTTPError as e:
            if deneme == 2:
                raise
            print(f"  KAP {e.code}; bekleniyor")
            time.sleep(90 if e.code == 429 else 15)
        except Exception as e:
            if deneme == 2:
                raise
            print("  KAP yanıt vermedi, yeniden denenecek:", str(e)[:100])
            time.sleep(15)


def liste_al(bugun):
    """Son GUN günün listesi; 2000 sınırına dayanırsa gün gün sorulur. (liste, tam mı)"""
    bas = bugun - datetime.timedelta(days=GUN - 1)
    L = kap_liste(bas, bugun)
    if len(L) < SINIR:
        return L, True
    L, tam = [], True
    for i in range(GUN):
        time.sleep(ARA)
        g = kap_liste(bas + datetime.timedelta(days=i), bas + datetime.timedelta(days=i))
        if len(g) >= SINIR:
            # Tek günde 2000+ bildirim: en yeniler gelir, o günün eskileri eksik kalabilir (günlük tarama yakalar)
            print(f"  UYARI: {bas + datetime.timedelta(days=i)} tek günde {len(g)} bildirim; liste eksik olabilir")
            tam = False
        L += g
    return L, tam


def guvenilir_mi(L):
    """Yanıt beklenen biçimde mi? Boş ya da alanları eksik liste 'yeni bildirim yok' diye yorumlanmaz."""
    if not L:
        return False
    return all(isinstance(x, dict) and "subject" in x and "stockCodes" in x and x.get("disclosureIndex") for x in L[:50])


def yayin_zamani(x):
    """KAP 'publishDate' alanı (GG.AA.YYYY SS:DD:SS, İstanbul saati) → datetime ya da None."""
    p = (x.get("publishDate") or "").strip()
    for bicim in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M"):
        try:
            return datetime.datetime.strptime(p, bicim).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def ilgili(L, kodlar, turler):
    """Bizim şirketlerimizin izlenen türdeki bildirimleri: {numara: kayıt}."""
    out = {}
    for x in L:
        tur = tur_bul(x.get("subject"))
        if not tur or not turler.get(tur, True):
            continue
        kod = next((k for k in (x.get("stockCodes") or "").replace(" ", "").split(",") if k in kodlar), None)
        if not kod:
            continue
        z = yayin_zamani(x)
        out[str(x["disclosureIndex"])] = {"tur": tur, "kod": kod, "konu": (x.get("subject") or "").strip(),
                                          "yayin": z.isoformat(timespec="seconds") if z else (x.get("publishDate") or "")}
    return out


def sayfa_yolu(tur, no):
    return os.path.join(HAM, tur, f"{SAYFA_TUR[tur][0]}{no}.html.gz")


def sayfa_al(no):
    """Bildirim sayfasının ham içeriği. 429'da beklemez (hata fırlatır); sonraki çalıştırma sürdürür."""
    basliklar = {"User-Agent": UA, "Accept": "text/html, application/json, */*", "Accept-Language": "tr",
                 "Origin": "https://kap.org.tr", "Referer": "https://kap.org.tr/tr/"}
    with urllib.request.urlopen(urllib.request.Request(SAYFA + str(no), headers=basliklar), timeout=SAYFA_ZAMAN) as r:
        return r.read()


def sayfalari_indir(G, D, ayar):
    """Kayıttaki bildirimlerden sayfası istenen türde olup dosyası olmayanları indirir (yeniden eskiye, en çok SAYFA_EN_COK).
    İndirilen sayısı. Kayıttan düşen (60 günden eski) bildirimlerin dosyaları silinir."""
    acik = ayar.get("sayfa") or {}
    deneme = D.setdefault("sayfa_deneme", {})
    kalan = sorted((no for no, k in G.items() if k.get("tur") in SAYFA_TUR and acik.get(k["tur"], False)
                    and not os.path.exists(sayfa_yolu(k["tur"], no)) and deneme.get(no, 0) < SAYFA_DENEME), key=int, reverse=True)
    n = 0
    bitis = time.monotonic() + SAYFA_BUTCE
    for i, no in enumerate(kalan[:SAYFA_EN_COK]):
        tur = G[no]["tur"]
        if i:
            time.sleep(SAYFA_ARA)
        if time.monotonic() > bitis:
            print("  sayfa: süre bütçesi doldu; kalanlar sonraki tura")
            break
        try:
            v = sayfa_al(no)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                # KAP "yavaşla" diyor: beklemeden bırak, sonraki tur sürdürür (deneme sayılmaz)
                print(f"  sayfa {no}: KAP {e.code}; sayfa indirme bu turda bırakıldı")
                break
            deneme[no] = deneme.get(no, 0) + 1
            print(f"  sayfa {no}: KAP {e.code} (deneme {deneme[no]}/{SAYFA_DENEME})")
            continue
        except Exception as e:
            deneme[no] = deneme.get(no, 0) + 1
            print(f"  sayfa {no}: alınamadı ({str(e)[:80]})")
            continue
        if len(v) < 500 or SAYFA_TUR[tur][1] not in v:
            deneme[no] = deneme.get(no, 0) + 1
            print(f"  sayfa {no}: bildirim biçiminde değil ({len(v)} bayt); kaydedilmedi (deneme {deneme[no]}/{SAYFA_DENEME})")
            continue
        yol = sayfa_yolu(tur, no)
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol + ".yeni", "wb") as f:
            f.write(gzip.compress(v, 6))
        os.replace(yol + ".yeni", yol)
        deneme.pop(no, None)
        n += 1
    for no in [no for no in deneme if no not in G]:
        del deneme[no]
    for tur, (onek, _) in SAYFA_TUR.items():
        klasor = os.path.join(HAM, tur)
        for ad in (os.listdir(klasor) if os.path.isdir(klasor) else []):
            if ad.startswith(onek) and ad.endswith(".html.gz") and ad[len(onek):-8] not in G:
                os.remove(os.path.join(klasor, ad))
    if kalan:
        print(f"sayfa: bekleyen {len(kalan)}, bu turda indirilen {n}")
    return n


def kodlari_yenile(ayar):
    """Şirket listesi günde bir kez siteden yenilenir (yeni eklenen şirketler için). Olmazsa eldeki liste kullanılır."""
    kayit = oku(KODLAR, [])
    kodlar = kayit if isinstance(kayit, list) else kayit.get("kodlar", [])
    tarih = None if isinstance(kayit, list) else kayit.get("tarih")
    bugun = simdi().date().isoformat()
    if tarih != bugun:
        try:
            with urllib.request.urlopen(urllib.request.Request(SIRKETLER, headers={"User-Agent": UA}), timeout=30) as r:
                yeni = sorted({x["kod"] for x in json.loads(r.read().decode("utf-8"))["sirketler"]})
            if len(yeni) >= 400 and len(yeni) >= len(kodlar) * 0.9:
                if yeni != kodlar:
                    print(f"şirket listesi yenilendi: {len(kodlar)} → {len(yeni)}")
                kodlar = yeni
                yaz(KODLAR, {"tarih": bugun, "kodlar": kodlar})
        except Exception as e:
            print("şirket listesi yenilenemedi, eldeki kullanılıyor:", str(e)[:100])
    return set(kodlar)


def main():
    ayar = oku(AYAR, {})
    if not ayar.get("acik", False):
        print("Nöbetçi kapalı (ayar.json acik=false); KAP'a istek gönderilmedi.")
        return 0
    kodlar = kodlari_yenile(ayar)
    if len(kodlar) < 400:
        print("HATA: şirket listesi yok ya da eksik.", file=sys.stderr)
        return 1
    an = simdi()
    try:
        L, tam = liste_al(an.date())
    except Exception as e:
        print("HATA: KAP listesi alınamadı:", str(e)[:200], file=sys.stderr)
        return 1
    if not guvenilir_mi(L):
        print(f"HATA: KAP listesi beklenen biçimde değil ({len(L)} kayıt); kayıt değiştirilmedi.", file=sys.stderr)
        return 1
    bulunan = ilgili(L, kodlar, ayar.get("turler") or {})
    D = oku(GORULEN, None)
    ilk = D is None
    if ilk:
        D = {"aciklama": "Nöbetçinin gördüğü bildirimler: KAP bildirim numarası → tür, şirket, KAP yayın saati, nöbetçinin ilk gördüğü saat",
             "bildirim": {}}
    G = D["bildirim"]
    # Sonradan eklenen bir tür ilk turunda eldeki 3 günün bildirimlerini getirir; onlar da "önceden vardı" sayılır
    bilinen = set(TUM_TURLER) if ilk else set(D.get("turler") or ["bilanco", "temettu", "yeni_is"])
    yeni_tur = set(TUM_TURLER) - bilinen
    yeni = []
    for no, k in sorted(bulunan.items(), key=lambda t: t[1]["yayin"]):
        if no in G:
            continue
        # İlk çalıştırmada eldeki 3 günün bildirimleri "önceden vardı" diye işaretlenir (gecikme ölçümüne girmez)
        k["gorulme"] = None if (ilk or k["tur"] in yeni_tur) else an.isoformat(timespec="seconds")
        G[no] = k
        yeni.append((no, k))
    # Eski kayıtları at
    esik = (an - datetime.timedelta(days=SAKLA_GUN)).isoformat()
    for no in [no for no, k in G.items() if (k.get("yayin") or "9") < esik]:
        del G[no]
    print(f"KAP listesi: {len(L)} bildirim{'' if tam else ' (eksik olabilir)'}; izlenen türde bizim şirketlerden {len(bulunan)}; yeni {len(yeni)}")
    for no, k in yeni:
        gecikme = ""
        if k["gorulme"]:
            try:
                dk = (an - datetime.datetime.fromisoformat(k["yayin"])).total_seconds() / 60
                gecikme = f" · yayından {dk:.0f} dk sonra görüldü"
            except ValueError:
                pass
        print(f"  yeni: {no} {k['tur']} {k['kod']} (KAP {k['yayin']}){gecikme}")
    onceki_deneme = json.dumps(D.get("sayfa_deneme") or {}, sort_keys=True)
    sayfalari_indir(G, D, ayar)
    if yeni or ilk or yeni_tur or json.dumps(D.get("sayfa_deneme") or {}, sort_keys=True) != onceki_deneme:
        D["turler"] = TUM_TURLER
        D["guncelleme"] = an.isoformat(timespec="seconds")
        yaz(GORULEN, D)
    if not ayar.get("kuru", True):
        # Hızlı iş henüz yok (sonraki aşama). Kuru çalışma dışında bir şey yapılmaz.
        print("Not: 'kuru' kapalı ama tetikleme henüz yazılmadı; yalnız kayıt tutuldu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
