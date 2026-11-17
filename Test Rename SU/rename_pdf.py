import fitz
import re
from pathlib import Path
from collections import Counter

# ==========================================
# KONFIGURASI (ganti per folder / per buku)
# ==========================================

NAMA_DESA = "SILURAH"
TAHUN = "2022"

# True = beri peringatan jika nomor tidak sejajar dengan urutan nama file.
# Matikan (False) kalau urutan nama file memang tidak berhubungan dengan nomor.
CEK_URUTAN = True

# Untuk file yang OCR-nya tidak bisa dibaca sama sekali, isi nomor manual lalu
# jalankan ulang. Kunci = nama file ASLI (tanpa awalan "NEED ACTION 001 - ").
KOREKSI_MANUAL = {
    # "HM-01422-DESA_SILURAH.pdf": "01305",
}

# ==========================================
# POLA
# ==========================================

FOLDER = Path(__file__).resolve().parent

# Karakter yang sering salah dibaca OCR sebagai angka
K = r"[0-9OoQDIl|!Zz]"
# Karakter yang sering salah dibaca OCR sebagai "/"
SEP = r"[/\\|!lItT1]"
# 5 karakter nomor, boleh ada satu spasi nyasar di antaranya
NOMOR5 = rf"((?:{K} ?){{4}}{K})"

POLA_BERTINGKAT = [
    # Level 0: 5 karakter + pemisah + kata berawalan S + tahun
    re.compile(
        rf"(?<![0-9A-Za-z]){NOMOR5} ?{SEP} ?[Ss]\S{{3,14}}?"
        rf"(?: ?{SEP})? ?[2Zz][0OoQD][0-9OoIl]{{2}}"
    ),
    # Level 1: label "Nomor" + 5 karakter + pemisah
    re.compile(rf"[Nn][Oo][Mm][Oo][Rr] ?[:;.]? ?{NOMOR5} ?{SEP}"),
    # Level 2: 5 angka + "/" asli + huruf
    re.compile(r"(?<![0-9A-Za-z/])([0-9]{5}) ?/ ?[A-Za-z\[{(]"),
]
KETERANGAN_LEVEL = [
    "",
    "pola longgar: nama desa/tahun tidak terbaca",
    "pola longgar: hanya cocok angka + garis miring",
]

KOREKSI_OCR = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "|": "1", "!": "1",
    "Z": "2", "z": "2",
})

POLA_NAMA_SUDAH_BENAR = re.compile(
    rf"^\d{{5}} {re.escape(NAMA_DESA)} {re.escape(TAHUN)}\.pdf$",
    re.IGNORECASE
)
POLA_PREFIX = re.compile(r"^NEED ACTION \d{3} - (.+)$", re.IGNORECASE)


# ==========================================
# FUNGSI BANTU
# ==========================================

def nama_asli(nama):
    m = POLA_PREFIX.match(nama)
    return m.group(1) if m else nama


def buat_nama_file(nomor):
    return f"{nomor} {NAMA_DESA} {TAHUN}.pdf"


def buat_nama_need_action(pdf_path, terpakai):
    angka = 1
    while True:
        nama = f"NEED ACTION {angka:03d} - {nama_asli(pdf_path.name)}"
        tujuan = FOLDER / nama
        if not tujuan.exists() and nama.lower() not in terpakai:
            terpakai.add(nama.lower())
            return tujuan
        angka += 1


def cuplikan_ocr(teks):
    """Tampilkan teks yang muncul setelah kata 'Nomor' (maks 5 tempat)."""
    datar = re.sub(r"\s+", " ", teks).strip()
    potongan = []
    for m in re.finditer(r"nomor", datar, re.IGNORECASE):
        isi = datar[m.end(): m.end() + 35].strip()
        if isi:
            potongan.append(isi)
        if len(potongan) >= 5:
            break
    if potongan:
        return " || ".join(potongan)
    return datar[:100] if datar else "(tidak ada teks)"


def baca_teks(pdf_path):
    """Baca halaman 1 dalam dua urutan baca (biasa dan terurut posisi)."""
    with fitz.open(pdf_path) as dok:
        if len(dok) == 0:
            return None
        hal = dok[0]
        hasil = [hal.get_text("text")]
        try:
            hasil.append(hal.get_text("text", sort=True))
        except Exception:
            pass
    return hasil


def cari_kandidat(teks):
    datar = re.sub(r"\s+", " ", teks)
    for level, pola in enumerate(POLA_BERTINGKAT):
        ditemukan = pola.findall(datar)
        if ditemukan:
            return level, ditemukan
    return None, []


def ambil_nomor(pdf_path):
    """Return (nomor, daftar_catatan, error)."""
    try:
        daftar_teks = baca_teks(pdf_path)
    except Exception as e:
        return None, [], f"GAGAL MEMBACA PDF ({e})"

    if daftar_teks is None:
        return None, [], "PDF KOSONG"
    if not any(t.strip() for t in daftar_teks):
        return None, [], "TIDAK ADA TEKS OCR DI HALAMAN 1"

    level, mentah_list = None, []
    for teks in daftar_teks:
        level, mentah_list = cari_kandidat(teks)
        if mentah_list:
            break

    if not mentah_list:
        return None, [], (
            "NOMOR TIDAK DITEMUKAN | teks setelah 'Nomor': "
            + cuplikan_ocr(daftar_teks[0])
        )

    pasangan = {}
    for m in mentah_list:
        tanpa = m.replace(" ", "")
        pasangan.setdefault(tanpa.translate(KOREKSI_OCR), (m, tanpa))

    if len(pasangan) > 1:
        return None, [], f"BANYAK KANDIDAT NOMOR ({', '.join(pasangan)})"

    nomor, (mentah, tanpa) = next(iter(pasangan.items()))

    if not re.fullmatch(r"\d{5}", nomor):
        return None, [], f"NOMOR TIDAK VALID ({mentah})"
    if sum(c.isdigit() for c in tanpa) < 3:
        return None, [], f"NOMOR MENCURIGAKAN ({mentah})"

    catatan = []
    if tanpa != nomor:
        catatan.append(f"huruf dikoreksi dari '{tanpa}'")
    if " " in mentah:
        catatan.append("spasi di dalam nomor dibuang")
    if level and level > 0:
        catatan.append(KETERANGAN_LEVEL[level])
    return nomor, catatan, None


def di_luar_urutan(angka):
    """Indeks yang keluar dari urutan naik terpanjang."""
    n = len(angka)
    if n == 0:
        return set()
    panjang = [1] * n
    induk = [-1] * n
    for i in range(n):
        for j in range(i):
            if angka[j] < angka[i] and panjang[j] + 1 > panjang[i]:
                panjang[i] = panjang[j] + 1
                induk[i] = j
    akhir = max(range(n), key=lambda k: panjang[k])
    aman = set()
    while akhir != -1:
        aman.add(akhir)
        akhir = induk[akhir]
    return set(range(n)) - aman


def petunjuk_urutan(rencana, i):
    """Nomor tetangga terdekat (yang aman) sebagai petunjuk manual."""
    def aman(it):
        return it["status"] == "SIAP" and not it["catatan"]
    sebelum = next((rencana[j]["nomor"] for j in range(i - 1, -1, -1)
                    if aman(rencana[j])), None)
    sesudah = next((rencana[j]["nomor"] for j in range(i + 1, len(rencana))
                    if aman(rencana[j])), None)
    if sebelum or sesudah:
        return f"kira-kira antara {sebelum or '?'} dan {sesudah or '?'}"
    return None


# ==========================================
# PROGRAM UTAMA
# ==========================================

def main():
    if not re.fullmatch(r"\d{4}", TAHUN):
        print("ERROR: Tahun harus 4 digit.")
        return
    if not NAMA_DESA.strip():
        print("ERROR: Nama desa belum diisi.")
        return
    for k, v in KOREKSI_MANUAL.items():
        if not re.fullmatch(r"\d{5}", v):
            print(f"ERROR: Nomor manual untuk {k} harus 5 digit (isi: {v}).")
            return

    pdf_files = []
    for p in FOLDER.glob("*.pdf"):
        if not p.is_file():
            continue
        # File NEED ACTION diabaikan, kecuali sudah diisi di KOREKSI_MANUAL
        if p.name.upper().startswith("NEED ACTION") \
                and nama_asli(p.name) not in KOREKSI_MANUAL:
            continue
        pdf_files.append(p)
    pdf_files.sort(key=lambda p: nama_asli(p.name).lower())

    if not pdf_files:
        print("Tidak ada PDF baru untuk diproses.")
        return

    print("=" * 70)
    print("RENAME PDF SURAT UKUR")
    print("=" * 70)
    print(f"Folder : {FOLDER}")
    print(f"Format : 12345 {NAMA_DESA} {TAHUN}.pdf")
    print(f"Jumlah : {len(pdf_files)} PDF")
    print("=" * 70)

    # ---------- TAHAP 1: BACA ----------
    rencana = []
    for i, pdf in enumerate(pdf_files, 1):
        print(f"\rMembaca {i}/{len(pdf_files)}...", end="", flush=True)

        if POLA_NAMA_SUDAH_BENAR.fullmatch(pdf.name):
            rencana.append({"asal": pdf, "tujuan": pdf, "status": "SKIP",
                            "alasan": "", "catatan": []})
            continue

        asli = nama_asli(pdf.name)
        if asli in KOREKSI_MANUAL:
            nomor = KOREKSI_MANUAL[asli]
            rencana.append({"asal": pdf, "tujuan": FOLDER / buat_nama_file(nomor),
                            "status": "SIAP", "nomor": nomor, "alasan": "",
                            "catatan": [], "manual": True})
            continue

        nomor, catatan, error = ambil_nomor(pdf)
        if error:
            rencana.append({"asal": pdf, "tujuan": None, "status": "NEED ACTION",
                            "alasan": error, "catatan": []})
        else:
            rencana.append({"asal": pdf, "tujuan": FOLDER / buat_nama_file(nomor),
                            "status": "SIAP", "nomor": nomor, "alasan": "",
                            "catatan": catatan})
    print()

    # ---------- TAHAP 2: DUPLIKAT & BENTROK ----------
    hitung = Counter(it["nomor"] for it in rencana if it["status"] == "SIAP")
    for it in rencana:
        if it["status"] != "SIAP":
            continue
        if hitung[it["nomor"]] > 1:
            it["status"] = "NEED ACTION"
            it["alasan"] = f"NOMOR DUPLIKAT ({it['nomor']})"
        elif it["tujuan"].exists() and it["tujuan"] != it["asal"]:
            it["status"] = "NEED ACTION"
            it["alasan"] = "NAMA FILE TUJUAN SUDAH ADA"

    # ---------- TAHAP 3: CEK URUTAN ----------
    if CEK_URUTAN:
        idx = [i for i, it in enumerate(rencana) if it["status"] == "SIAP"]
        angka = [int(rencana[i]["nomor"]) for i in idx]
        for k in di_luar_urutan(angka):
            it = rencana[idx[k]]
            if not it.get("manual"):
                it["catatan"].append(
                    "nomor tidak sejajar dengan urutan nama file")

    # ---------- TAHAP 4: NAMA NEED ACTION ----------
    terpakai = set()
    for it in rencana:
        if it["status"] == "NEED ACTION":
            it["tujuan"] = buat_nama_need_action(it["asal"], terpakai)

    # ---------- TAHAP 5: PREVIEW ----------
    bersih = [x for x in rencana if x["status"] == "SIAP" and not x["catatan"]]
    cek = [x for x in rencana if x["status"] == "SIAP" and x["catatan"]]
    periksa = [(i, x) for i, x in enumerate(rencana)
               if x["status"] == "NEED ACTION"]
    skip = [x for x in rencana if x["status"] == "SKIP"]

    print(f"\n--- SIAP RENAME, BERSIH ({len(bersih)}) ---")
    for x in bersih:
        print(f"{x['asal'].name}  ->  {x['tujuan'].name}")

    if cek:
        print(f"\n--- SIAP, TAPI CEK DULU ({len(cek)}) ---")
        for x in cek:
            print(f"{x['asal'].name}  ->  {x['tujuan'].name}")
            for c in x["catatan"]:
                print(f"    ! {c}")

    if periksa:
        print(f"\n--- NEED ACTION ({len(periksa)}) ---")
        for i, x in periksa:
            print(x["asal"].name)
            print(f"    Alasan : {x['alasan']}")
            tip = petunjuk_urutan(rencana, i)
            if tip:
                print(f"    Urutan : {tip}")

    print("\n" + "=" * 70)
    print(f"Siap rename, bersih  : {len(bersih)}")
    print(f"Siap tapi cek dulu   : {len(cek)}")
    print(f"Need Action          : {len(periksa)}")
    print(f"Dilewati (sudah ok)  : {len(skip)}")
    print(f"Total                : {len(pdf_files)}")
    print("=" * 70)

    if not bersih and not cek and not periksa:
        print("Tidak ada perubahan yang perlu dilakukan.")
        return

    # ---------- TAHAP 6: KONFIRMASI ----------
    print("\nPilihan:")
    print("  Y = rename semua yang SIAP (termasuk 'cek dulu') + tandai NEED ACTION")
    print("  A = rename yang BERSIH saja + tandai NEED ACTION")
    print("      (yang 'cek dulu' dibiarkan, tidak diubah)")
    print("  N = batal")
    jawaban = input("Pilihan (Y/A/N): ").strip().upper()
    if jawaban not in ("Y", "A"):
        print("Dibatalkan. Tidak ada file yang diubah.")
        return

    # ---------- TAHAP 7: RENAME ----------
    berhasil = gagal = dibiarkan = 0
    print()
    for it in rencana:
        if it["status"] == "SKIP":
            continue
        if jawaban == "A" and it["status"] == "SIAP" and it["catatan"]:
            dibiarkan += 1
            continue
        asal, tujuan = it["asal"], it["tujuan"]
        try:
            if tujuan.exists():
                raise FileExistsError("File tujuan sudah ada.")
            asal.rename(tujuan)
            berhasil += 1
            print(f"[OK] {asal.name} -> {tujuan.name}")
        except Exception as e:
            gagal += 1
            print(f"[GAGAL] {asal.name} ({e})")

    print("\n" + "=" * 70)
    print(f"Berhasil  : {berhasil}")
    print(f"Gagal     : {gagal}")
    print(f"Dibiarkan : {dibiarkan}")
    print("=" * 70)


if __name__ == "__main__":
    main()
    input("\nTekan ENTER untuk keluar...")