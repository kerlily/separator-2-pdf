
import fitz
from pathlib import Path

FOLDER = Path(__file__).resolve().parent

# Ambil satu PDF pertama
pdf_files = sorted(FOLDER.glob("*.pdf"))

if not pdf_files:
    print("Tidak ada PDF!")
    raise SystemExit

pdf = pdf_files[0]

print("FILE:", pdf.name)

with fitz.open(pdf) as doc:
    page = doc[0]

    print("\n===== HASIL EKSTRAKSI OCR =====\n")

    print(page.get_text("text"))

    print("\n===== TEKS BESERTA KOORDINAT =====\n")

    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[:5]

        print(
            f"X:{x0:.1f} Y:{y0:.1f} "
            f"-> {repr(text)}"
        )

input("\nTekan ENTER...")
