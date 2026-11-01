import os
from flask import Flask, flash, redirect, render_template, request, url_for
import fitz  # PyMuPDF kütüphanesi

app = Flask(__name__)
app.secret_key = "gizli_anahtar_guvenlik_icin"

OGRETMEN_PDF = "Öğretmen Programı 13.pdf"
SINIF_PDF = "siniflarin_programi.pdf"

OGRETMEN_KLASORU = "static/ogretmenler"
SINIF_KLASORU = "static/siniflar"

os.makedirs(OGRETMEN_KLASORU, exist_ok=True)
os.makedirs(SINIF_KLASORU, exist_ok=True)


def ogretmen_temizle(metin):
  if not metin:
    return ""
  return (
      metin.replace("İ", "i")
      .replace("I", "ı")
      .replace("Ş", "ş")
      .replace("Ğ", "ğ")
      .replace("Ü", "ü")
      .replace("Ö", "ö")
      .replace("Ç", "ç")
      .lower()
  )


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
    listesi.append({"metin": ogretmen_temizle(text), "resim": resim_adi})
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


@app.route("/", methods=["GET", "POST"])
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
    rehber_tiklandi = request.form.get("rehber_goster")  # Yeni eklenen buton

    if pansiyon_tiklandi is not None:
      pansiyon_yolu = os.path.join("static", "pansiyon_nobet.png")
      if os.path.exists(pansiyon_yolu):
        secilen_resim = "pansiyon_nobet.png"
      else:
        flash("Henüz pansiyon nöbet listesi yüklenmemiş!", "warning")

    elif nobetci_tiklandi is not None:
      nobetci_yolu = os.path.join("static", "nobetci_ogretmen.png")
      if os.path.exists(nobetci_yolu):
        secilen_resim = "nobetci_ogretmen.png"
      else:
        flash("Henüz nöbetçi öğretmen listesi yüklenmemiş!", "warning")

    elif rehber_tiklandi is not None:  # Sınıf rehber öğretmenleri göster
      rehber_yolu = os.path.join("static", "rehber_ogretmenler.png")
      if os.path.exists(rehber_yolu):
        secilen_resim = "rehber_ogretmenler.png"
      else:
        flash("Henüz sınıf rehber öğretmenleri listesi yüklenmemiş!", "warning")

    elif ogretmen_input is not None:
      ogretmen_arama = ogretmen_input.strip()
      if ogretmen_arama:
        arama = ogretmen_temizle(ogretmen_arama)
        if "edip" in arama:
          secilen_resim = "ogretmenler/sayfa_1.png"
        else:
          for item in ogretmen_listesi:
            if arama in item["metin"]:
              secilen_resim = f"ogretmenler/{item['resim']}"
              break

    elif sinif_input is not None:
      sinif_arama = sinif_input.strip()
      if sinif_arama:
        arama = sinif_temizle(sinif_arama)
        for item in sinif_listesi:
          if arama == item["baslik"] or arama == item["baslik"].replace(" ", ""):
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


def sinif_bilgisi_getir(hedef_ad):
  hedef_temiz = sinif_temizle(hedef_ad)
  for item in sinif_listesi:
    if item["baslik"] == hedef_temiz or item["baslik"].replace(
        " ", ""
    ) == hedef_temiz.replace(" ", ""):
      return item
  for item in sinif_listesi:
    if hedef_temiz in item["baslik"]:
      return item
  return None


@app.route("/kat1")
def kat1():
  sol_liste = [
      sinif_bilgisi_getir(s) for s in KAT1_SOL if sinif_bilgisi_getir(s)
  ]
  sag_liste = [
      sinif_bilgisi_getir(s) for s in KAT1_SAG if sinif_bilgisi_getir(s)
  ]
  return render_template("kat1.html", sol_liste=sol_liste, sag_liste=sag_liste)


@app.route("/kat2")
def kat2():
  sol_liste = [
      sinif_bilgisi_getir(s) for s in KAT2_SOL if sinif_bilgisi_getir(s)
  ]
  sag_liste = [
      sinif_bilgisi_getir(s) for s in KAT2_SAG if sinif_bilgisi_getir(s)
  ]
  return render_template("kat2.html", sol_liste=sol_liste, sag_liste=sag_liste)


@app.route("/ayarlar", methods=["GET", "POST"])
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
        sinif_listesi, sinif_isimleri = sinif_pdf_isle(
            SINIF_PDF, SINIF_KLASORU
        )
        flash("Sınıf PDF dosyası başarıyla güncellendi!", "success")
      else:
        flash("Lütfen geçerli bir Sınıf PDF dosyası seçin!", "danger")
      return redirect(url_for("ayarlar"))

    if "pansiyon_pdf_dosyasi" in request.files:
      file = request.files["pansiyon_pdf_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join("static", "pansiyon_nobet.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join("static", "temp_pansiyon.pdf")
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
        hedef_resim_yolu = os.path.join("static", "nobetci_ogretmen.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join("static", "temp_nobet.pdf")
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

    # Sınıf Rehber Öğretmenleri Dosya Yükleme (PDF veya JPG/PNG)
    if "rehber_ogretmen_dosyasi" in request.files:
      file = request.files["rehber_ogretmen_dosyasi"]
      if file and file.filename != "":
        uzanti = file.filename.lower().rsplit(".", 1)[-1]
        hedef_resim_yolu = os.path.join("static", "rehber_ogretmenler.png")
        if uzanti == "pdf":
          temp_pdf = os.path.join("static", "temp_rehber.pdf")
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

  return render_template("ayarlar.html")


if __name__ == "__main__":
  app.run(debug=True)