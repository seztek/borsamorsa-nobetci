#!/usr/bin/env python3
"""borsamorsa.com nöbetçisi — KAP bildirim listesini 10 dakikada bir yoklar.

Ne yapar: KAP'ın herkese açık bildirim listesinden son 3 günü sorar (tek istek), borsamorsa.com'da izlenen şirketlerin
finansal rapor, kâr payı ve yeni iş ilişkisi bildirimlerini ayırır ve ilk kez gördüğü her bildirimi görülme saatiyle
durum/gorulen.json dosyasına yazar.

Şimdilik KURU ÇALIŞMA: yalnız kayıt tutar; hiçbir şeyi yayınlamaz, başka bir işi başlatmaz (ayar.json "kuru": true).
Amaç, nöbetçinin her bildirimi zamanında ve doğru gördüğünü günlük taramalarla karşılaştırarak kanıtlamak.

Kapatma anahtarı: ayar.json içinde "acik": false → KAP'a hiç istek gitmez.
KAP'a yük: çalıştırma başına 1 liste isteği (liste 2000 kayda dayanırsa gün gün, en çok 3 istek).

Kullanım: python3 nobetci.py            çıkış 0 (yeni bildirim olsa da olmasa da) · 1 KAP yanıt vermedi ya da liste güvenilmez
"""
import datetime, json, os, sys, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

KOK = os.path.dirname(os.path.abspath(__file__))
AYAR = os.path.join(KOK, "ayar.json")
KODLAR = os.path.join(KOK, "kodlar.json")
GORULEN = os.path.join(KOK, "durum", "gorulen.json")
KAP = "https://kap.org.tr/tr/api/disclosure/members/byCriteria"
SIRKETLER = "https://borsamorsa.com/data/sirketler.json"
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
}


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
        tur = TURLER.get((x.get("subject") or "").strip())
        if not tur or not turler.get(tur, True):
            continue
        kod = next((k for k in (x.get("stockCodes") or "").replace(" ", "").split(",") if k in kodlar), None)
        if not kod:
            continue
        z = yayin_zamani(x)
        out[str(x["disclosureIndex"])] = {"tur": tur, "kod": kod, "konu": (x.get("subject") or "").strip(),
                                          "yayin": z.isoformat(timespec="seconds") if z else (x.get("publishDate") or "")}
    return out


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
    yeni = []
    for no, k in sorted(bulunan.items(), key=lambda t: t[1]["yayin"]):
        if no in G:
            continue
        # İlk çalıştırmada eldeki 3 günün bildirimleri "önceden vardı" diye işaretlenir (gecikme ölçümüne girmez)
        k["gorulme"] = None if ilk else an.isoformat(timespec="seconds")
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
    if yeni or ilk:
        D["guncelleme"] = an.isoformat(timespec="seconds")
        yaz(GORULEN, D)
    if not ayar.get("kuru", True):
        # Hızlı iş henüz yok (sonraki aşama). Kuru çalışma dışında bir şey yapılmaz.
        print("Not: 'kuru' kapalı ama tetikleme henüz yazılmadı; yalnız kayıt tutuldu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
