
from pypdf import PdfReader, PdfWriter
from pathlib import Path

INPUT_FOLDER = Path("Scan")
OUTPUT_FOLDER = Path("Hasil_Pemisahan")

KODE = "HM"
DESA = "DESA_SILURAH"

NOMOR_AWAL = 1401

# Nomor yang ingin dilewati
SKIP_NOMOR = [
    
]

# =====================================
# PERSIAPAN FOLDER
# =====================================

OUTPUT_FOLDER.mkdir(exist_ok=True)

nomor = NOMOR_AWAL

# =====================================
# PROSES PEMISAHAN PDF
# =====================================

pdf_files = sorted(INPUT_FOLDER.glob("*.pdf"))

if not pdf_files:
    print("Tidak ada file PDF di folder Scan!")

else:
    for pdf_file in pdf_files:

        reader = PdfReader(pdf_file)
        total_pages = len(reader.pages)

        print("\n=================================")
        print(f"Memproses: {pdf_file.name}")
        print(f"Total halaman: {total_pages}")
        print("=================================")

        if total_pages % 2 != 0:
            print("PERINGATAN: Jumlah halaman ganjil!")

        for i in range(0, total_pages, 2):

            # Lewati nomor yang ditentukan
            while nomor in SKIP_NOMOR:
                print(f"Skip nomor: {nomor:05d}")
                nomor += 1

            writer = PdfWriter()

            # Halaman depan
            writer.add_page(reader.pages[i])

            # Halaman belakang
            if i + 1 < total_pages:
                writer.add_page(reader.pages[i + 1])

            # Format nama file
            nama_file = f"{KODE}-{nomor:05d}-{DESA}.pdf"

            output_path = OUTPUT_FOLDER / nama_file

            # Jangan timpa file yang sudah ada
            if output_path.exists():
                print(f"SKIP: File sudah ada: {nama_file}")
                continue

            # Simpan PDF
            with open(output_path, "wb") as f:
                writer.write(f)

            print(f"Berhasil: {nama_file}")

            nomor += 1

# =====================================
# SELESAI
# =====================================

print("\n=================================")
print("SEMUA PROSES SELESAI!")
print("=================================")

input("Tekan ENTER untuk keluar...")
