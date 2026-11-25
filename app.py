import datetime
from functools import wraps
import os
import re
import sqlite3
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
import pymupdf as fitz  # PyMuPDF kütüphanesi
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "/var/data" if os.path.exists("/var/data") else BASE_DIR
DATABASE = os.path.join(DATA_DIR, "sinif.db")

app = Flask(__name__, root_path=BASE_DIR)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "ordu_karsiyaka_mahallesi52"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Tek kullanıcı kimlik bilgileri (parola hashlenerek saklanır)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("dolunay_serinsok52")

MEZUN_YILLARI = [
    "2018/2019 Mezun",
    "2019/2020 Mezun",
    "2020/2021 Mezun",
    "2021/2022 Mezun",
    "2022/2023 Mezun",
    "2023/2024 Mezun",
    "2024/2025 Mezun",
    "2025/2026 Mezun",
]

# İsteğe bağlı özel ad / kod eşleştirmeleri
OGRETMEN_KISAYOLLARI = {
    "ayh": "yasemin ayhan",
    "y.ayh": "yasemin ayhan",
    "kdr": "kadir düzel",
    "k.dzl": "kadir düzel",
    "krp": "r.krp",
    "r.krp": "r.krp",
    "kbb": "g.kbb",
    "g.kbb": "g.kbb",
    "krm": "fatma karaman",
    "f.krm": "fatma karaman",
}


def get_db():
  db = getattr(g, "_database", None)
  if db is None:
    db = g._database = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
  return db


@app.teardown_appcontext
def close_connection(exception):
  db = getattr(g, "_database", None)
  if db is not None:
    db.close()


def init_db():
  os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
  with app.app_context():
    db = get_db()
    db.execute("""
            CREATE TABLE IF NOT EXISTS siniflar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad TEXT UNIQUE NOT NULL
            )
        """)
    db.execute("""
            CREATE TABLE IF NOT EXISTS ders_programi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sinif_id INTEGER,
                gun TEXT,
                saat INTEGER,
                ders_adi TEXT,
                FOREIGN KEY (sinif_id) REFERENCES siniflar(id) ON DELETE CASCADE
            )
        """)
    db.execute("""
            CREATE TABLE IF NOT EXISTS ders_saatleri (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ders_sirasi INTEGER,
                giris_saati TEXT,
                cikis_saati TEXT
            )
        """)
    db.execute("""
            CREATE TABLE IF NOT EXISTS mezunlar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_soyad TEXT NOT NULL,
                mezuniyet_yili TEXT NOT NULL,
                resim_yolu TEXT,
                aciklama TEXT DEFAULT ''
            )
        """)
    db.commit()


init_db()

STATIC_DIR = os.path.join(BASE_DIR, "static")
OGRETMEN_PDF = os.path.join(STATIC_DIR, "ogretmen_programi.pdf")
SINIF_PDF = os.path.join(STATIC_DIR, "sinif_programi.pdf")

OGRETMEN_KLASORU = os.path.join(STATIC_DIR, "ogretmenler")
SINIF_KLASORU = os.path.join(STATIC_DIR, "siniflar")
MEZUN_FOTOLAR_KLASORU = os.path.join(STATIC_DIR, "mezun_fotolari")

os.makedirs(OGRETMEN_KLASORU, exist_ok=True)
os.makedirs(SINIF_KLASORU, exist_ok=True)
os.makedirs(MEZUN_FOTOLAR_KLASORU, exist_ok=True)


# --- OTURUM YÖNETİMİ ---
def login_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if not session.get("logged_in"):
      if request.path.startswith("/api/"):
        return jsonify({"error": "Oturum gerekli"}), 401
      return redirect(url_for("login", next=request.path))
    return f(*args, **kwargs)

  return decorated_function


@app.before_request
def require_login_for_all_pages():
  acik_rotalar = {"login", "static"}
  if request.endpoint in acik_rotalar or request.endpoint is None:
    return None
  if not session.get("logged_in"):
    if request.path.startswith("/api/"):
      return jsonify({"error": "Oturum gerekli"}), 401
    return redirect(url_for("login", next=request.path))
  return None


@app.context_processor
def inject_user_info():
  return {"aktif_kullanici": session.get("username", "")}


@app.route("/login", methods=["GET", "POST"])
def login():
  if session.get("logged_in"):
    return redirect(url_for("index"))

  if request.method == "POST":
    kullanici_adi = request.form.get("username", "").strip()
    parola = request.form.get("password", "")

    if kullanici_adi == ADMIN_USERNAME and check_password_hash(
        ADMIN_PASSWORD_HASH, parola
    ):
      session.clear()
      session["logged_in"] = True
      session["username"] = ADMIN_USERNAME
      next_url = request.form.get("next") or request.args.get("next")
      if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
      return redirect(url_for("index"))
    else:
      flash("Kullanıcı adı veya parola hatalı!", "danger")

  next_page = request.args.get("next", "")
  return render_template("login.html", next_page=next_page)


@app.route("/logout")
@login_required
def logout():
  session.clear()
  flash("Oturumunuz güvenli şekilde kapatıldı.", "info")
  return redirect(url_for("login"))


# --- TÜRKİYE SAATİNİ SABİTLEYEN YARDIMCI FONKSİYON ---
def turkiye_zamani_al():
  utc_zaman = datetime.datetime.utcnow()
  turkiye_zamani = utc_zaman + datetime.timedelta(hours=3)
  return turkiye_zamani


def tr_buyuk(metin):
  if not metin:
    return ""
  return (
      metin.replace("i", "İ")
      .replace("ı", "I")
      .replace("ç", "Ç")
      .replace("ğ", "Ğ")
      .replace("ö", "Ö")
      .replace("ş", "Ş")
      .replace("ü", "Ü")
      .upper()
  )


def ogretmen_temizle(metin):
  if not metin:
    return ""
  temiz = (
      metin.replace("İ", "i")
      .replace("I", "ı")
      .replace("Ş", "ş")
      .replace("Ğ", "ğ")
      .replace("Ü", "ü")
      .replace("Ö", "ö")
      .replace("Ç", "ç")
      .lower()
  )
  return re.sub(r"\s+", " ", temiz).strip()


def noktasiz_metin(metin):
  if not metin:
    return ""
  return re.sub(r"[.\s\-_()]+", "", ogretmen_temizle(metin))


def sessiz_harfler(metin):
  """Kelimedeki sesli harfleri çıkararak yld, mst gibi kısaltma iskeletini üretir."""
  temiz = ogretmen_temizle(metin)
  if not temiz:
    return ""
  return re.sub(r"[aeıioöuü.\s\-_()]+", "", temiz)


def noktadan_sonraki_kod(metin):
  if not metin:
    return ""
  ham = metin.strip()
  if "." in ham:
    son_parca = ham.split(".")[-1].strip()
    son_parca = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü0-9]", "", son_parca)
    return tr_buyuk(son_parca)
  return tr_buyuk(re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü0-9]", "", ham))


def ogretmen_aramasini_coz(ham_arama):
  temiz = ogretmen_temizle(ham_arama)
  if not temiz:
    return []

  adaylar = []

  if "." in temiz:
    noktadan_sonra = re.sub(
        r"[^a-zçğıöşü0-9]", "", temiz.split(".")[-1].strip()
    )
    if noktadan_sonra:
      adaylar.append(noktadan_sonra)
      if noktadan_sonra in OGRETMEN_KISAYOLLARI:
        adaylar.append(ogretmen_temizle(OGRETMEN_KISAYOLLARI[noktadan_sonra]))

  adaylar.append(temiz)
  if temiz in OGRETMEN_KISAYOLLARI:
    adaylar.append(ogretmen_temizle(OGRETMEN_KISAYOLLARI[temiz]))

  ek_adaylar = []
  for a in adaylar:
    ek_adaylar.append(a)
    ek_adaylar.append(a.replace(".", " "))
    ek_adaylar.append(a.replace(".", ""))

  sirali_adaylar = []
  for a in ek_adaylar:
    a_temiz = ogretmen_temizle(a)
    if a_temiz and a_temiz not in sirali_adaylar:
      sirali_adaylar.append(a_temiz)
  return sirali_adaylar


def ogretmen_kodu_cikar(ders_adi):
  """Ders metnindeki en sondaki öğretmen ifadesinin (örn. H.SLK, C.KST) noktadan sonraki kısmını (SLK, KST) döndürür."""
  if not ders_adi:
    return ""
  buyuk_metin = tr_buyuk(ders_adi.strip())

  son_kod = re.search(
      r"(?:^|\s)([A-ZÇĞİÖŞÜ]{1,3}\d?\s*\.\s*[A-ZÇĞİÖŞÜ]{2,6})\s*\)?\s*$",
      buyuk_metin,
  )
  if son_kod:
    tam_kod = re.sub(r"\s+", "", son_kod.group(1))
    return tam_kod.split(".")[-1].strip()

  tum_kodlar = re.findall(
      r"\b[A-ZÇĞİÖŞÜ]{1,3}\d?\s*\.\s*([A-ZÇĞİÖŞÜ]{2,6})\b", buyuk_metin
  )
  if tum_kodlar:
    return tum_kodlar[-1].strip()

  tek_kod = re.search(r"\b([A-ZÇĞİÖŞÜ]{2,5})\s*\)?\s*$", buyuk_metin)
  if tek_kod:
    aday = tek_kod.group(1).strip()
    if aday not in {
        "DERS",
        "BOŞ",
        "BOS",
        "YOK",
        "PTS",
        "SAL",
        "ÇAR",
        "PER",
        "CUM",
    }:
      return aday

  return ""


def sinif_temizle(metin):
  if not metin:
    return ""
  temiz = ogretmen_temizle(metin)
  return (
      temiz.replace(" ", "")
      .replace("-", "")
      .replace("/", "")
      .replace(":", "")
      .replace(".", "")
  )


def ogretmen_pdf_isle(pdf_yolu, hedef_klasor):
  listesi = []
  if not os.path.exists(pdf_yolu):
    return listesi
  doc = fitz.open(pdf_yolu)
  for sayfa_no in range(len(doc)):
    page = doc[sayfa_no]
    text = page.get_text()
    pix = page.get_pixmap(dpi=150)
    resim_adi = f"sayfa_{sayfa_no}.png"
    pix.save(os.path.join(hedef_klasor, resim_adi))
    temiz_metin = ogretmen_temizle(text)
    kelimeler = re.findall(r"[a-zçğıöşü]+", temiz_metin)
    listesi.append({
        "metin": temiz_metin,
        "noktasiz": noktasiz_metin(temiz_metin),
        "kelimeler": kelimeler,
        "kelime_sessizleri": [sessiz_harfler(k) for k in kelimeler],
        "resim": resim_adi,
    })
  return listesi


def sinif_pdf_isle(pdf_yolu, hedef_klasor):
  sinif_listesi = []
  ham_siniflar = []
  if not os.path.exists(pdf_yolu):
    return sinif_listesi, ham_siniflar

  doc = fitz.open(pdf_yolu)
  for sayfa_no in range(len(doc)):
    page = doc[sayfa_no]
    text = page.get_text()
    pix = page.get_pixmap(dpi=150)
    resim_adi = f"sayfa_{sayfa_no}.png"
    pix.save(os.path.join(hedef_klasor, resim_adi))

    satirlar = text.split("\n")
    sinif_adi = ""

    for satir in satirlar:
      s = satir.strip().lstrip(":").strip()
      s_kucuk = s.lower()
      if not s or len(s) > 25:
        continue
      if any(
          kelime in s_kucuk
          for kelime in [
              "t.c.",
              "kaymakamliği",
              "valiliği",
              "müdürlüğü",
              "lisesi",
              "ortaokulu",
              "ders",
              "programı",
              "gün",
          ]
      ):
        continue
      if any(c.isdigit() for c in s):
        sinif_adi = s
        break

    if not sinif_adi:
      sinif_adi = f"Sayfa {sayfa_no+1}"

    ham_siniflar.append(sinif_adi)
    sinif_listesi.append({
        "baslik": sinif_temizle(sinif_adi),
        "orijinal_baslik": sinif_adi,
        "resim": resim_adi,
        "tum_metin": sinif_temizle(text),
    })

  return sinif_listesi, sorted(list(set(ham_siniflar)))


ogretmen_listesi = ogretmen_pdf_isle(OGRETMEN_PDF, OGRETMEN_KLASORU)
sinif_listesi, sinif_isimleri = sinif_pdf_isle(SINIF_PDF, SINIF_KLASORU)

KAT1_SOL = ["12ÇGL", "10Yih", "9Yih"]
KAT1_SAG = ["11yih", "10a", "9a"]
KAT2_SOL = ["12a", "11a"]
KAT2_SAG = []


def zaman_dakika_farki(saat_str1, saat_str2):
  h1, m1 = map(int, saat_str1.split(":"))
  h2, m2 = map(int, saat_str2.split(":"))
  return (h2 * 60 + m2) - (h1 * 60 + m1)


def genel_okul_durumu_getir(db):
  simdi = turkiye_zamani_al()
  simdi_time = simdi.strftime("%H:%M")

  saatler = db.execute(
      "SELECT * FROM ders_saatleri ORDER BY ders_sirasi"
  ).fetchall()
  if not saatler:
    return {"mesaj_ust": "Ders Saatleri Tanımlı Değil", "mesaj_alt": ""}

  for s in saatler:
    g_saat = s["giris_saati"]
    c_saat = s["cikis_saati"]
    sirasi = s["ders_sirasi"]

    if not g_saat or not c_saat:
      continue

    if g_saat <= simdi_time <= c_saat:
      kalan_dakika = zaman_dakika_farki(simdi_time, c_saat)
      return {
          "mesaj_ust": f"Şu an <strong>{sirasi}.</strong> dersteyiz.",
          "mesaj_alt": (
              f"Teneffüs ziline <span"
              f" style='font-size:22px;'><strong>{kalan_dakika}</strong></span>"
              " dakika var."
          ),
          "tip": "ders",
      }

  for i in range(len(saatler) - 1):
    c_suanki = saatler[i]["cikis_saati"]
    g_sonraki = saatler[i + 1]["giris_saati"]
    sonraki_sirasi = saatler[i + 1]["ders_sirasi"]

    if c_suanki <= simdi_time < g_sonraki:
      kalan_dakika = zaman_dakika_farki(simdi_time, g_sonraki)
      return {
          "mesaj_ust": "Şu an teneffüsteyiz.",
          "mesaj_alt": (
              f"<strong>{sonraki_sirasi}.</strong> ders ziline <span"
              f" style='font-size:22px;'><strong>{kalan_dakika}</strong></span>"
              " dakika var."
          ),
          "tip": "tenefus",
      }

  if saatler and simdi_time < saatler[0]["giris_saati"]:
    kalan_dakika = zaman_dakika_farki(simdi_time, saatler[0]["giris_saati"])
    return {
        "mesaj_ust": "Dersler henüz başlamadı.",
        "mesaj_alt": (
            f"<strong>1.</strong> ders ziline <span"
            f" style='font-size:22px;'><strong>{kalan_dakika}</strong></span>"
            " dakika var."
        ),
        "tip": "tenefus",
    }

  return {
      "mesaj_ust": "Bugünkü dersler sona erdi.",
      "mesaj_alt": "İyi akşamlar dileriz.",
      "tip": "tenefus",
  }


def guncel_ders_bilgisi_ve_durum(sinif_adi, db):
  gun_kodlari = {
      0: "PTS",
      1: "SAL",
      2: "ÇAR",
      3: "PER",
      4: "CUM",
      5: "CTS",
      6: "PAZ",
  }
  simdi = turkiye_zamani_al()
  bugun_kod = gun_kodlari.get(simdi.weekday(), "PTS")
  simdi_time = simdi.strftime("%H:%M")

  temiz_aranan = sinif_temizle(sinif_adi)
  tum_siniflar = db.execute("SELECT id, ad FROM siniflar").fetchall()
  sinif_id = None

  for s in tum_siniflar:
    db_ad_temiz = sinif_temizle(s["ad"])
    if (
        temiz_aranan == db_ad_temiz
        or temiz_aranan in db_ad_temiz
        or db_ad_temiz in temiz_aranan
    ):
      sinif_id = s["id"]
      break

  if not sinif_id:
    return "Ders Programı Girilmemiş", None, ""

  saatler = db.execute(
      "SELECT * FROM ders_saatleri ORDER BY ders_sirasi"
  ).fetchall()
  if not saatler:
    return "Ders Saatleri Tanımlı Değil", None, ""

  aktif_ders_sirasi = None
  for s in saatler:
    g_saat = s["giris_saati"]
    c_saat = s["cikis_saati"]
    sirasi = s["ders_sirasi"]
    if not g_saat or not c_saat:
      continue
    if g_saat <= simdi_time <= c_saat:
      aktif_ders_sirasi = sirasi
      break

  if not aktif_ders_sirasi:
    for s in saatler:
      g_saat = s["giris_saati"]
      if g_saat and simdi_time < g_saat:
        aktif_ders_sirasi = s["ders_sirasi"]
        break
    if not aktif_ders_sirasi and saatler:
      aktif_ders_sirasi = 1

  ders_row = db.execute(
      "SELECT ders_adi FROM ders_programi WHERE sinif_id = ? AND gun = ? AND"
      " saat = ?",
      (sinif_id, bugun_kod, aktif_ders_sirasi),
  ).fetchone()

  if ders_row and ders_row["ders_adi"]:
    ders_metni = ders_row["ders_adi"].strip()
    ogretmen_kodu = ogretmen_kodu_cikar(ders_metni)
    return (
        f"{aktif_ders_sirasi}. Ders: {ders_metni}",
        aktif_ders_sirasi,
        ogretmen_kodu,
    )
  else:
    return f"{aktif_ders_sirasi}. Ders: Boş / Ders Yok", aktif_ders_sirasi, ""


def sinif_bilgisi_getir(hedef_ad, db):
  hedef_temiz_str = sinif_temizle(hedef_ad)
  bulunan_pdf_item = None
  for item in sinif_listesi:
    if (
        item["baslik"] == hedef_temiz_str
        or item["baslik"].replace(" ", "") == hedef_temiz_str.replace(" ", "")
        or hedef_temiz_str in item["baslik"]
        or item["baslik"] in hedef_temiz_str
    ):
      bulunan_pdf_item = item
      break

  anlik_ders, _, ogretmen_kodu = guncel_ders_bilgisi_ve_durum(hedef_ad, db)

  if bulunan_pdf_item:
    kopya_item = dict(bulunan_pdf_item)
    kopya_item["anlik_ders"] = anlik_ders
    kopya_item["ogretmen_kodu"] = ogretmen_kodu
    return kopya_item
  else:
    return {
        "orijinal_baslik": hedef_ad,
        "resim": "",
        "anlik_ders": anlik_ders,
        "ogretmen_kodu": ogretmen_kodu,
    }


def ogretmen_resmi_bul(ogretmen_sorgusu):
  if not ogretmen_sorgusu:
    return None

  adaylar = ogretmen_aramasini_coz(ogretmen_sorgusu)

  for arama in adaylar:
    if "edip" in arama:
      return "ogretmenler/sayfa_1.png"

  # 1. Doğrudan tam veya noktasız metin eşleşmesi
  for arama in adaylar:
    arama_noktasiz = noktasiz_metin(arama)
    for item in ogretmen_listesi:
      metin_noktasiz = item.get("noktasiz") or noktasiz_metin(item["metin"])
      if arama in item["metin"] or (
          arama_noktasiz and arama_noktasiz in metin_noktasiz
      ):
        return f"ogretmenler/{item['resim']}"

  # 2. Kısaltma / sessiz harf eşleşmesi (örn. yld -> yildirim, mst -> mustafa)
  for arama in adaylar:
    arama_sessiz = sessiz_harfler(arama)
    if len(arama_sessiz) >= 2:
      for item in ogretmen_listesi:
        kelime_sessizleri = item.get("kelime_sessizleri") or [
            sessiz_harfler(k) for k in re.findall(r"[a-zçğıöşü]+", item["metin"])
        ]
        if any(ks.startswith(arama_sessiz) for ks in kelime_sessizleri):
          return f"ogretmenler/{item['resim']}"

  return None


@app.route("/debug-ogretmen")
@login_required
def debug_ogretmen():
  if not os.path.exists(OGRETMEN_PDF):
    return "<pre>ogretmen_programi.pdf bulunamadı.</pre>"
  doc = fitz.open(OGRETMEN_PDF)
  cikti = []
  for i, page in enumerate(doc):
    cikti.append(f"=== SAYFA {i} (sayfa_{i}.png) ===\n{page.get_text()}")
  return f"<pre>{''.join(cikti)}</pre>"


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
  global ogretmen_listesi, sinif_listesi, sinif_isimleri
  secilen_resim = None
  ogretmen_arama = ""
  sinif_arama = ""

  if request.method == "POST":
    ogretmen_input = request.form.get("ogretmen")
    sinif_input = request.form.get("sinif")
    pansiyon_tiklandi = request.form.get("pansiyon_goster")
    nobetci_tiklandi = request.form.get("nobetci_goster")
    rehber_tiklandi = request.form.get("rehber_goster")
    klup_tiklandi = request.form.get("klup_goster")
    sinav_tiklandi = request.form.get("sinav_goster")
    blok_tiklandi = request.form.get("blok_goster")
    imamhatip_tiklandi = request.form.get("imamhatip_goster")
    ogrenci_sayilari_tiklandi = request.form.get("ogrenci_sayilari_goster")
    calisma_takvimi_tiklandi = request.form.get("calisma_takvimi_goster")
    calisma_takvimi1_tiklandi = request.form.get("calisma_takvimi1_goster")

    if pansiyon_tiklandi is not None:
      pansiyon_yolu = os.path.join(STATIC_DIR, "pansiyon_nobet.png")
      if os.path.exists(pansiyon_yolu):
        secilen_resim = "pansiyon_nobet.png"
      else:
        flash("Henüz pansiyon nöbet listesi yüklenmemiş!", "warning")

    elif nobetci_tiklandi is not None:
      nobetci_yolu = os.path.join(STATIC_DIR, "nobetci_ogretmen.png")
      if os.path.exists(nobetci_yolu):
        secilen_resim = "nobetci_ogretmen.png"
      else:
        flash("Henüz nöbetçi öğretmen listesi yüklenmemiş!", "warning")

    elif rehber_tiklandi is not None:
      rehber_yolu = os.path.join(STATIC_DIR, "rehber_ogretmenler.png")
      if os.path.exists(rehber_yolu):
        secilen_resim = "rehber_ogretmenler.png"
      else:
        flash("Henüz sınıf rehber öğretmenleri listesi yüklenmemiş!", "warning")

    elif klup_tiklandi is not None:
      klup_yolu = os.path.join(STATIC_DIR, "klup_ogretmenleri.png")
      if os.path.exists(klup_yolu):
        secilen_resim = "klup_ogretmenleri.png"
      else:
        flash("Henüz kulüp öğretmenleri listesi yüklenmemiş!", "warning")

    elif sinav_tiklandi is not None:
      sinav_yolu = os.path.join(STATIC_DIR, "sinav_programi.png")
      if os.path.exists(sinav_yolu):
        secilen_resim = "sinav_programi.png"
      else:
        flash("Henüz sınav programı yüklenmemiş!", "warning")

    elif blok_tiklandi is not None:
      blok_yolu = os.path.join(STATIC_DIR, "blok_saatler.png")
      if os.path.exists(blok_yolu):
        secilen_resim = "blok_saatler.png"
      else:
        flash("Henüz blok saatler listesi yüklenmemiş!", "warning")

    elif imamhatip_tiklandi is not None:
      imamhatip_yolu = os.path.join(STATIC_DIR, "imamhatip_saatler.png")
      if os.path.exists(imamhatip_yolu):
        secilen_resim = "imamhatip_saatler.png"
      else:
        flash("Henüz imamhatip saatler listesi yüklenmemiş!", "warning")

    elif ogrenci_sayilari_tiklandi is not None:
      ogrenci_yolu = os.path.join(STATIC_DIR, "ogrenci_sayilari.png")
      if os.path.exists(ogrenci_yolu):
        secilen_resim = "ogrenci_sayilari.png"
      else:
        flash("Henüz öğrenci sayıları listesi yüklenmemiş!", "warning")

    elif calisma_takvimi_tiklandi is not None:
      takvim_yolu = os.path.join(STATIC_DIR, "calisma_takvimi.png")
      if os.path.exists(takvim_yolu):
        secilen_resim = "calisma_takvimi.png"
      else:
        flash("Henüz çalışma takvimi yüklenmemiş!", "warning")

    elif calisma_takvimi1_tiklandi is not None:
      takvim1_yolu = os.path.join(STATIC_DIR, "calisma_takvimi1.png")
      if os.path.exists(takvim1_yolu):
        secilen_resim = "calisma_takvimi1.png"
      else:
        flash("Henüz Çalışma Takvimi 1 yüklenmemiş!", "warning")

    elif ogretmen_input is not None:
      ham_girdi = ogretmen_input.strip()
      if "." in ham_girdi:
        ogretmen_arama = noktadan_sonraki_kod(ham_girdi)
      else:
        ogretmen_arama = ham_girdi

      if ogretmen_arama:
        secilen_resim = ogretmen_resmi_bul(ogretmen_arama)
        if not secilen_resim:
          flash(
              f"'{ogretmen_arama}' için öğretmen programı bulunamadı!",
              "warning",
          )
      else:
        flash("Bu ders için öğretmen kodu bulunamadı!", "warning")

    elif sinif_input is not None:
      sinif_arama = sinif_input.strip()
      if sinif_arama:
        arama = sinif_temizle(sinif_arama)
        for item in sinif_listesi:
          if arama == item["baslik"] or arama == item["baslik"].replace(
              " ", ""
          ):
            secilen_resim = f"siniflar/{item['resim']}"
            break
        if not secilen_resim:
          for item in sinif_listesi:
            if arama in item["baslik"]:
              secilen_resim = f"siniflar/{item['resim']}"
              break

  return render_template(
      "index.html",
      secilen_resim=secilen_resim,
      ogretmen_arama=ogretmen_arama,
      sinif_arama=sinif_arama,
      sinif_isimleri=sinif_isimleri,
  )


@app.route("/kat1")
@login_required
def kat1():
  db = get_db()
  sol_liste = [
      sinif_bilgisi_getir(s, db) for s in KAT1_SOL if sinif_bilgisi_getir(s, db)
  ]
  sag_liste = [
      sinif_bilgisi_getir(s, db) for s in KAT1_SAG if sinif_bilgisi_getir(s, db)
  ]
  okul_durumu = genel_okul_durumu_getir(db)
  return render_template(
      "kat1.html",
      sol_liste=sol_liste,
      sag_liste=sag_liste,
      okul_durumu=okul_durumu,
  )


@app.route("/kat2")
@login_required
def kat2():
  db = get_db()
  sol_liste = [
      sinif_bilgisi_getir(s, db) for s in KAT2_SOL if sinif_bilgisi_getir(s, db)
  ]
  sag_liste = [
      sinif_bilgisi_getir(s, db) for s in KAT2_SAG if sinif_bilgisi_getir(s, db)
  ]
  okul_durumu = genel_okul_durumu_getir(db)
  return render_template(
      "kat2.html",
      sol_liste=sol_liste,
      sag_liste=sag_liste,
      okul_durumu=okul_durumu,
  )


@app.route("/mezunlar", methods=["GET", "POST"])
@login_required
def mezunlar():
  db = get_db()
  secilen_yil = ""
  aciklama_arama = ""
  ad_arama = ""
  sonuclar = []
  liste_basligi = ""

  if request.method == "POST":
    if "aciklama_kaydet_id" in request.form:
      mezun_id = request.form.get("aciklama_kaydet_id")
      yeni_aciklama = request.form.get("aciklama_metni", "").strip()
      db.execute(
          "UPDATE mezunlar SET aciklama = ? WHERE id = ?",
          (yeni_aciklama, mezun_id),
      )
      db.commit()
      flash("Öğrenci açıklaması kaydedildi!", "success")

      secilen_yil = request.form.get("aktif_yil", "")
      aciklama_arama = request.form.get("aktif_aciklama_arama", "")
      ad_arama = tr_buyuk(request.form.get("aktif_ad_arama", ""))

      if aciklama_arama:
        sonuclar = db.execute(
            "SELECT * FROM mezunlar WHERE aciklama LIKE ? ORDER BY ad_soyad"
            " ASC",
            (f"%{aciklama_arama}%",),
        ).fetchall()
        liste_basligi = f"Açıklama Aramasına Göre Sonuçlar: '{aciklama_arama}'"
      elif secilen_yil:
        sonuclar = db.execute(
            "SELECT * FROM mezunlar WHERE mezuniyet_yili = ? ORDER BY ad_soyad"
            " ASC",
            (secilen_yil,),
        ).fetchall()
        liste_basligi = f"{secilen_yil} Öğrencileri"
      elif ad_arama:
        aranan = tr_buyuk(ad_arama)
        tum_kayitlar = db.execute(
            "SELECT * FROM mezunlar ORDER BY mezuniyet_yili DESC, ad_soyad ASC"
        ).fetchall()
        sonuclar = [
            r for r in tum_kayitlar if aranan in tr_buyuk(r["ad_soyad"])
        ]
        liste_basligi = f"İsim Aramasına Göre Sonuçlar: '{ad_arama}'"

    elif "aciklama_ara_btn" in request.form:
      aciklama_arama = request.form.get("aciklama_arama", "").strip()
      if aciklama_arama:
        sonuclar = db.execute(
            "SELECT * FROM mezunlar WHERE aciklama LIKE ? ORDER BY"
            " mezuniyet_yili DESC, ad_soyad ASC",
            (f"%{aciklama_arama}%",),
        ).fetchall()
        liste_basligi = f"Açıklama Aramasına Göre Sonuçlar: '{aciklama_arama}'"
      else:
        flash("Lütfen açıklamaya göre arama yapmak için metin girin!", "warning")

    elif "yil_sec_btn" in request.form:
      secilen_yil = request.form.get("mezun_yili", "").strip()
      if secilen_yil:
        sonuclar = db.execute(
            "SELECT * FROM mezunlar WHERE mezuniyet_yili = ? ORDER BY ad_soyad"
            " ASC",
            (secilen_yil,),
        ).fetchall()
        liste_basligi = f"{secilen_yil} Öğrencileri"
      else:
        flash("Lütfen bir mezuniyet yılı seçin!", "warning")

    elif "ad_ara_btn" in request.form:
      ad_arama = tr_buyuk(request.form.get("ad_soyad_arama", "").strip())
      if ad_arama:
        aranan = tr_buyuk(ad_arama)
        tum_kayitlar = db.execute(
            "SELECT * FROM mezunlar ORDER BY mezuniyet_yili DESC, ad_soyad ASC"
        ).fetchall()
        sonuclar = [
            r for r in tum_kayitlar if aranan in tr_buyuk(r["ad_soyad"])
        ]
        liste_basligi = f"Ad / Soyad Aramasına Göre Sonuçlar: '{ad_arama}'"
      else:
        flash("Lütfen öğrenci adı veya soyadı girin!", "warning")

  return render_template(
      "mezunlar.html",
      mezun_yillari=MEZUN_YILLARI,
      secilen_yil=secilen_yil,
      aciklama_arama=aciklama_arama,
      ad_arama=ad_arama,
      sonuclar=sonuclar,
      liste_basligi=liste_basligi,
  )


@app.route("/api/mezun-ara")
@login_required
def api_mezun_ara():
  q = request.args.get("q", "").strip()
  if not q:
    return jsonify([])
  aranan = tr_buyuk(q)
  db = get_db()
  rows = db.execute("SELECT * FROM mezunlar ORDER BY ad_soyad ASC").fetchall()
  eslesenler = [dict(r) for r in rows if aranan in tr_buyuk(r["ad_soyad"])][
      :15
  ]
  return jsonify(eslesenler)


@app.route("/ders_programi_yukle", methods=["GET", "POST"])
@login_required
def ders_programi_yukle():
  db = get_db()

  if request.method == "POST":
    islem = request.form.get("islem")

    if islem == "yeni_sinif":
      sinif_adi = request.form.get("sinif_adi", "").strip()
      if sinif_adi:
        try:
          db.execute("INSERT INTO siniflar (ad) VALUES (?)", (sinif_adi,))
          db.commit()
          flash(f"'{sinif_adi}' sınıfı başarıyla eklendi.", "success")
        except sqlite3.IntegrityError:
          flash(f"'{sinif_adi}' adında bir sınıf zaten mevcut!", "danger")
      return redirect(url_for("ders_programi_yukle"))

    elif islem == "sil_sinif":
      sinif_id = request.form.get("sinif_id")
      db.execute("DELETE FROM siniflar WHERE id = ?", (sinif_id,))
      db.execute("DELETE FROM ders_programi WHERE sinif_id = ?", (sinif_id,))
      db.commit()
      flash("Sınıf ve ders programı silindi.", "info")
      return redirect(url_for("ders_programi_yukle"))

    elif islem == "kaydet_program":
      sinif_id = request.form.get("sinif_id")
      gunler = ["PTS", "SAL", "ÇAR", "PER", "CUM", "CTS", "PAZ"]
      db.execute("DELETE FROM ders_programi WHERE sinif_id = ?", (sinif_id,))

      for gun in gunler:
        for saat in range(1, 12):
          ders_degeri = request.form.get(f"cell_{gun}_{saat}", "").strip()
          if ders_degeri:
            db.execute(
                "INSERT INTO ders_programi (sinif_id, gun, saat, ders_adi)"
                " VALUES (?, ?, ?, ?)",
                (sinif_id, gun, saat, ders_degeri),
            )
      db.commit()
      flash("Ders programı başarıyla kaydedildi.", "success")
      return redirect(url_for("ders_programi_yukle", aktif_sinif=sinif_id))

  siniflar = db.execute("SELECT * FROM siniflar ORDER BY ad").fetchall()

  aktif_sinif_id = request.args.get("aktif_sinif")
  if not aktif_sinif_id and siniflar:
    aktif_sinif_id = siniflar[0]["id"]

  aktif_sinif = None
  program_verileri = {}

  if aktif_sinif_id:
    aktif_sinif = db.execute(
        "SELECT * FROM siniflar WHERE id = ?", (aktif_sinif_id,)
    ).fetchone()
    p_rows = db.execute(
        "SELECT gun, saat, ders_adi FROM ders_programi WHERE sinif_id = ?",
        (aktif_sinif_id,),
    ).fetchall()
    for row in p_rows:
      if row["gun"] not in program_verileri:
        program_verileri[row["gun"]] = {}
      program_verileri[row["gun"]][row["saat"]] = row["ders_adi"]

  return render_template(
      "ders_programi_yukle.html",
      siniflar=siniflar,
      aktif_sinif=aktif_sinif,
      program_verileri=program_verileri,
  )


@app.route("/ders_saatleri", methods=["GET", "POST"])
@login_required
def ders_saatleri():
  db = get_db()
  if request.method == "POST":
    db.execute("DELETE FROM ders_saatleri")
    for i in range(1, 21):
      giris = request.form.get(f"giris_{i}")
      cikis = request.form.get(f"cikis_{i}")
      if giris or cikis:
        db.execute(
            "INSERT INTO ders_saatleri (ders_sirasi, giris_saati, cikis_saati)"
            " VALUES (?, ?, ?)",
            (i, giris, cikis),
        )
    db.commit()
    flash("Ders saatleri başarıyla güncellendi!", "success")
    return redirect(url_for("ders_saatleri"))

  saatler = db.execute(
      "SELECT * FROM ders_saatleri ORDER BY ders_sirasi"
  ).fetchall()
  return render_template("ders_saatleri.html", saatler=saatler)


@app.route("/ayarlar", methods=["GET", "POST"])
@login_required
def ayarlar():
  global ogretmen_listesi, sinif_listesi, sinif_isimleri

  if request.method == "POST":
    if "ogretmen_pdf_dosyasi" in request.files:
      file = request.files["ogretmen_pdf_dosyasi"]
      if file and file.filename.endswith(".pdf"):
        file.save(OGRETMEN_PDF)
        ogretmen_listesi = ogretmen_pdf_isle(OGRETMEN_PDF, OGRETMEN_KLASORU)
        flash("Öğretmen PDF dosyası başarıyla güncellendi!", "success")
      else:
        flash("Lütfen geçerli bir Öğretmen PDF dosyası seçin!", "danger")
      return redirect(url_for("ayarlar"))

    if "sinif_pdf_dosyasi" in request.files:
      file = request.files["sinif_pdf_dosyasi"]
      if file and file.filename.endswith(".pdf"):
        file.save(SINIF_PDF)
        sinif_listesi, sinif_isimleri = sinif_pdf_isle(SINIF_PDF, SINIF_KLASORU)
        flash("Sınıf PDF dosyası başarıyla güncellendi!", "success")
      else:
        flash("Lütfen geçerli bir Sınıf PDF dosyası seçin!", "danger")
      return redirect(url_for("ayarlar"))

    if "pansiyon_pdf_dosyasi" in request.files:
      file = request.files["pansiyon_pdf_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join(STATIC_DIR, "pansiyon_nobet.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join(STATIC_DIR, "temp_pansiyon.pdf")
          file.save(temp_pdf)
          doc = fitz.open(temp_pdf)
          if len(doc) > 0:
            doc[0].get_pixmap(dpi=150).save(hedef_resim_yolu)
          doc.close()
          if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        elif uzanti in ["jpg", "jpeg", "png"]:
          file.save(hedef_resim_yolu)
        flash("Pansiyon nöbet listesi güncellendi!", "success")
      return redirect(url_for("ayarlar"))

    if "nobetci_ogretmen_dosyasi" in request.files:
      file = request.files["nobetci_ogretmen_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join(STATIC_DIR, "nobetci_ogretmen.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join(STATIC_DIR, "temp_nobet.pdf")
          file.save(temp_pdf)
          doc = fitz.open(temp_pdf)
          if len(doc) > 0:
            doc[0].get_pixmap(dpi=150).save(hedef_resim_yolu)
          doc.close()
          if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        elif uzanti in ["jpg", "jpeg", "png"]:
          file.save(hedef_resim_yolu)
        flash("Nöbetçi öğretmen listesi güncellendi!", "success")
      return redirect(url_for("ayarlar"))

    if "rehber_ogretmen_dosyasi" in request.files:
      file = request.files["rehber_ogretmen_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join(STATIC_DIR, "rehber_ogretmenler.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join(STATIC_DIR, "temp_rehber.pdf")
          file.save(temp_pdf)
          doc = fitz.open(temp_pdf)
          if len(doc) > 0:
            doc[0].get_pixmap(dpi=150).save(hedef_resim_yolu)
          doc.close()
          if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        elif uzanti in ["jpg", "jpeg", "png"]:
          file.save(hedef_resim_yolu)
        flash("Sınıf rehber öğretmenleri listesi güncellendi!", "success")
      return redirect(url_for("ayarlar"))

    if "klup_ogretmen_dosyasi" in request.files:
      file = request.files["klup_ogretmen_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join(STATIC_DIR, "klup_ogretmenleri.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join(STATIC_DIR, "temp_klup.pdf")
          file.save(temp_pdf)
          doc = fitz.open(temp_pdf)
          if len(doc) > 0:
            doc[0].get_pixmap(dpi=150).save(hedef_resim_yolu)
          doc.close()
          if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        elif uzanti in ["jpg", "jpeg", "png"]:
          file.save(hedef_resim_yolu)
        flash("Kulüp öğretmenleri listesi güncellendi!", "success")
      return redirect(url_for("ayarlar"))

    if "sinav_programi_dosyasi" in request.files:
      file = request.files["sinav_programi_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join(STATIC_DIR, "sinav_programi.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join(STATIC_DIR, "temp_sinav.pdf")
          file.save(temp_pdf)
          doc = fitz.open(temp_pdf)
          if len(doc) > 0:
            doc[0].get_pixmap(dpi=150).save(hedef_resim_yolu)
          doc.close()
          if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        elif uzanti in ["jpg", "jpeg", "png"]:
          file.save(hedef_resim_yolu)
        flash("Sınav programı güncellendi!", "success")
      return redirect(url_for("ayarlar"))

  return render_template("ayarlar.html")


if __name__ == "__main__":
  app.run(debug=False, use_reloader=False)