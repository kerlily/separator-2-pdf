import base64
import re
from collections import Counter
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import fitz

# ==========================================
# KONFIGURASI (ganti per folder / per buku)
# ==========================================
NAMA_DESA = "SILURAH"
TAHUN = "2022"

FOLDER = Path(__file__).resolve().parent

# ==========================================
# POLA OCR
# ==========================================
K = r"[0-9OoQDIl|!Zz]"
SEP = r"[/\\|!lItT1]"
NOMOR5 = rf"((?:{K} ?){{4}}{K})"

POLA = [
    re.compile(
        rf"(?<![0-9A-Za-z]){NOMOR5} ?{SEP} ?[Ss]\S{{3,14}}?"
        rf"(?: ?{SEP})? ?[2Zz][0OoQD][0-9OoIl]{{2}}"
    ),
    re.compile(rf"[Nn][Oo][Mm][Oo][Rr] ?[:;.]? ?{NOMOR5} ?{SEP}"),
    re.compile(r"(?<![0-9A-Za-z/])([0-9]{5}) ?/ ?[A-Za-z\[{(]"),
]
KET_LEVEL = [
    None,
    "pola longgar: nama desa/tahun tidak terbaca",
    "pola longgar: hanya cocok angka + garis miring",
]
KOREKSI = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "|": "1", "!": "1",
    "Z": "2", "z": "2",
})
POLA_SUDAH = re.compile(
    rf"^(\d{{5}}) {re.escape(NAMA_DESA)} {re.escape(TAHUN)}\.pdf$",
    re.IGNORECASE,
)


def tebak_nomor(path):
    """Return (nomor, catatan). nomor None = tidak yakin; catatan = alasan."""
    try:
        with fitz.open(path) as d:
            if len(d) == 0:
                return None, ["PDF kosong"]
            h = d[0]
            daftar = [h.get_text("text")]
            try:
                daftar.append(h.get_text("text", sort=True))
            except Exception:
                pass
    except Exception as e:
        return None, [f"Gagal membaca PDF ({e})"]

    if not any(t.strip() for t in daftar):
        return None, ["Tidak ada teks OCR di halaman 1"]

    for teks in daftar:
        datar = re.sub(r"\s+", " ", teks)
        for level, pola in enumerate(POLA):
            hasil = pola.findall(datar)
            if not hasil:
                continue
            pasang = {}
            for m in hasil:
                tanpa = m.replace(" ", "")
                pasang.setdefault(tanpa.translate(KOREKSI), (m, tanpa))
            if len(pasang) > 1:
                return None, ["Banyak kandidat: " + ", ".join(pasang)]
            nomor, (mentah, tanpa) = next(iter(pasang.items()))
            if not re.fullmatch(r"\d{5}", nomor):
                return None, [f"Nomor tidak valid ({mentah})"]
            if sum(c.isdigit() for c in tanpa) < 3:
                return None, [f"Nomor mencurigakan ({mentah})"]
            cat = []
            if tanpa != nomor:
                cat.append(f"huruf dikoreksi dari '{tanpa}'")
            if " " in mentah:
                cat.append("spasi di dalam nomor dibuang")
            if KET_LEVEL[level]:
                cat.append(KET_LEVEL[level])
            return nomor, cat
    return None, ["Nomor tidak terbaca"]


# ==========================================
# APLIKASI
# ==========================================
LABEL = {"OK": "✔ OK", "CEK": "? CEK", "MANUAL": "✖ MANUAL", "SUDAH": "• SUDAH"}


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"Rename Surat Ukur — {NAMA_DESA} {TAHUN}")
        root.geometry("1450x820")

        self.items = []
        self.cur = None
        self.mode = "zoom"
        self.undo_stack = []
        self.foto = None

        self.bangun_ui()
        self.muat_semua()

    # ---------- UI ----------
    def bangun_ui(self):
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True)

        kiri = ttk.Frame(pane)
        kanan = ttk.Frame(pane)
        pane.add(kiri, weight=0)
        pane.add(kanan, weight=1)

        self.lbl_ringkas = ttk.Label(kiri, text="", padding=6)
        self.lbl_ringkas.pack(fill="x")

        kolom = ("file", "nomor", "status")
        self.tree = ttk.Treeview(kiri, columns=kolom, show="headings",
                                 selectmode="browse", height=30)
        self.tree.heading("file", text="File")
        self.tree.heading("nomor", text="Nomor")
        self.tree.heading("status", text="Status")
        self.tree.column("file", width=210)
        self.tree.column("nomor", width=65, anchor="center")
        self.tree.column("status", width=80, anchor="center")
        sb = ttk.Scrollbar(kiri, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("OK", background="#d6f5d6")
        self.tree.tag_configure("CEK", background="#fff3b0")
        self.tree.tag_configure("MANUAL", background="#ffd0d0")
        self.tree.tag_configure("SUDAH", background="#e3e3e3", foreground="#777")
        self.tree.bind("<<TreeviewSelect>>", self.saat_pilih)

        # kanan atas: info
        self.lbl_file = ttk.Label(kanan, text="", font=("Segoe UI", 12, "bold"),
                                  padding=(8, 6))
        self.lbl_file.pack(fill="x")
        self.lbl_catatan = tk.Label(kanan, text="", anchor="w", justify="left",
                                    font=("Segoe UI", 10), padx=8)
        self.lbl_catatan.pack(fill="x")
        self.lbl_tetangga = ttk.Label(kanan, text="", padding=(8, 2))
        self.lbl_tetangga.pack(fill="x")

        # kanan tengah: gambar
        self.gambar = tk.Label(kanan, bg="#888")
        self.gambar.pack(fill="both", expand=True, padx=8, pady=6)

        # kanan bawah: input
        bawah = ttk.Frame(kanan, padding=8)
        bawah.pack(fill="x")

        ttk.Label(bawah, text="Nomor (5 digit):",
                  font=("Segoe UI", 11)).pack(side="left")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(bawah, textvariable=self.var, width=8,
                               font=("Consolas", 22), justify="center")
        self.entry.pack(side="left", padx=8)
        self.lbl_hasil = ttk.Label(bawah, text="", font=("Segoe UI", 10))
        self.lbl_hasil.pack(side="left", padx=6)
        self.var.trace_add("write", lambda *a: self.update_pratinjau())

        ttk.Button(bawah, text="Rename + Lanjut (Enter)",
                   command=self.rename_sekarang).pack(side="left", padx=4)

        baris2 = ttk.Frame(kanan, padding=(8, 0, 8, 8))
        baris2.pack(fill="x")
        ttk.Button(baris2, text="◀ Sebelumnya",
                   command=lambda: self.pindah(-1)).pack(side="left")
        ttk.Button(baris2, text="Lewati ▶",
                   command=lambda: self.pindah(+1)).pack(side="left", padx=4)
        ttk.Button(baris2, text="Zoom / Halaman penuh (Tab)",
                   command=self.ganti_mode).pack(side="left", padx=12)
        ttk.Button(baris2, text="Undo (Ctrl+Z)",
                   command=self.undo).pack(side="left")
        ttk.Button(baris2, text="Rename semua yang hijau",
                   command=self.rename_hijau).pack(side="right")

        self.entry.bind("<Return>", lambda e: self.rename_sekarang())
        self.entry.bind("<Tab>", lambda e: (self.ganti_mode(), "break")[1])
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-Right>", lambda e: self.pindah(+1))
        self.root.bind("<Control-Left>", lambda e: self.pindah(-1))

    # ---------- DATA ----------
    def muat_semua(self):
        pdfs = sorted((p for p in FOLDER.glob("*.pdf") if p.is_file()),
                      key=lambda p: p.name.lower())
        if not pdfs:
            messagebox.showinfo("Kosong", "Tidak ada PDF di folder ini.")
            return

        for i, p in enumerate(pdfs, 1):
            self.root.title(f"Membaca {i}/{len(pdfs)} ...")
            self.root.update_idletasks()
            m = POLA_SUDAH.match(p.name)
            if m:
                self.items.append({"path": p, "nomor": m.group(1),
                                   "catatan": [], "status": "SUDAH"})
                continue
            nomor, cat = tebak_nomor(p)
            if nomor is None:
                self.items.append({"path": p, "nomor": None,
                                   "catatan": cat, "status": "MANUAL"})
            else:
                self.items.append({"path": p, "nomor": nomor, "catatan": cat,
                                   "status": "CEK" if cat else "OK"})

        # cek nomor dobel
        sudah = {it["nomor"] for it in self.items if it["status"] == "SUDAH"}
        hitung = Counter(it["nomor"] for it in self.items
                         if it["status"] in ("OK", "CEK"))
        for it in self.items:
            if it["status"] in ("OK", "CEK") and (
                    hitung[it["nomor"]] > 1 or it["nomor"] in sudah):
                it["catatan"].append("nomor dobel / sudah dipakai file lain")
                it["status"] = "CEK"

        self.root.title(f"Rename Surat Ukur — {NAMA_DESA} {TAHUN}")
        for i in range(len(self.items)):
            self.tree.insert("", "end", iid=str(i), values=("", "", ""))
            self.segarkan_baris(i)
        self.segarkan_ringkas()

        awal = next((i for i, it in enumerate(self.items)
                     if it["status"] != "SUDAH"), 0)
        self.pilih(awal)

    def segarkan_baris(self, i):
        it = self.items[i]
        self.tree.item(str(i), values=(it["path"].name, it["nomor"] or "",
                                       LABEL[it["status"]]),
                       tags=(it["status"],))

    def segarkan_ringkas(self):
        c = Counter(it["status"] for it in self.items)
        self.lbl_ringkas.config(
            text=f"Total {len(self.items)}  |  OK {c['OK']}  |  CEK {c['CEK']}"
                 f"  |  MANUAL {c['MANUAL']}  |  SUDAH {c['SUDAH']}")

    # ---------- NAVIGASI ----------
    def pilih(self, i):
        i = max(0, min(i, len(self.items) - 1))
        self.tree.selection_set(str(i))
        self.tree.see(str(i))
        self.tree.focus(str(i))

    def saat_pilih(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.cur = int(sel[0])
        it = self.items[self.cur]
        self.var.set(it["nomor"] or "")
        self.lbl_file.config(text=it["path"].name)

        warna = {"OK": "#1b7a1b", "CEK": "#9a6b00",
                 "MANUAL": "#b00020", "SUDAH": "#666"}[it["status"]]
        teks = {"OK": "Tebakan OCR yakin — cocokkan dengan gambar.",
                "SUDAH": "File ini sudah ter-rename."}.get(it["status"])
        if it["catatan"]:
            teks = "⚠ " + "; ".join(it["catatan"])
        self.lbl_catatan.config(text=teks or "", fg=warna)

        self.lbl_tetangga.config(text=self.teks_tetangga(self.cur))
        self.render()
        self.entry.focus_set()
        self.entry.selection_range(0, "end")

    def pindah(self, d):
        if self.cur is not None:
            self.pilih(self.cur + d)

    def ke_berikutnya_belum(self):
        n = len(self.items)
        for k in list(range(self.cur + 1, n)) + list(range(0, self.cur)):
            if self.items[k]["status"] != "SUDAH":
                self.pilih(k)
                return
        messagebox.showinfo("Selesai", "Semua file sudah ter-rename 🎉")

    def teks_tetangga(self, i):
        def cari(rentang):
            for j in rentang:
                if self.items[j]["nomor"]:
                    return self.items[j]["nomor"]
            return "?"
        sebelum = cari(range(i - 1, -1, -1))
        sesudah = cari(range(i + 1, len(self.items)))
        return f"Nomor tetangga: sebelumnya {sebelum}  |  berikutnya {sesudah}"

    # ---------- GAMBAR ----------
    def ganti_mode(self):
        self.mode = "penuh" if self.mode == "zoom" else "zoom"
        self.render()

    def render(self):
        if self.cur is None:
            return
        path = self.items[self.cur]["path"]
        try:
            with fitz.open(path) as d:
                page = d[0]
                r = page.rect
                if self.mode == "zoom":
                    clip = fitz.Rect(r.x0 + r.width * 0.45, r.y0,
                                     r.x1, r.y0 + r.height * 0.40)
                    zoom = 950 / clip.width
                else:
                    clip = r
                    zoom = min(950 / r.width, 640 / r.height)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
                data = base64.b64encode(pix.tobytes("png"))
            self.foto = tk.PhotoImage(data=data)
            self.gambar.config(image=self.foto, text="")
        except Exception as e:
            self.foto = None
            self.gambar.config(image="", text=f"Gagal menampilkan PDF: {e}",
                               fg="white")

    # ---------- RENAME ----------
    def nama_baru(self, nomor):
        return FOLDER / f"{nomor} {NAMA_DESA} {TAHUN}.pdf"

    def update_pratinjau(self):
        n = self.var.get().strip()
        if re.fullmatch(r"\d{5}", n):
            self.lbl_hasil.config(text=f"→ {n} {NAMA_DESA} {TAHUN}.pdf")
        else:
            self.lbl_hasil.config(text="(harus 5 digit angka)")

    def lakukan_rename(self, i, nomor):
        it = self.items[i]
        baru = self.nama_baru(nomor)
        if baru == it["path"]:
            return True
        if baru.exists():
            return f"File tujuan sudah ada: {baru.name}"
        try:
            lama = it["path"]
            lama.rename(baru)
        except Exception as e:
            return str(e)
        self.undo_stack.append((i, lama, baru, dict(it, catatan=list(it["catatan"]))))
        it["path"] = baru
        it["nomor"] = nomor
        it["catatan"] = []
        it["status"] = "SUDAH"
        self.segarkan_baris(i)
        return True

    def rename_sekarang(self):
        if self.cur is None:
            return
        nomor = self.var.get().strip()
        if not re.fullmatch(r"\d{5}", nomor):
            messagebox.showwarning("Nomor salah", "Nomor harus tepat 5 digit angka.")
            return
        hasil = self.lakukan_rename(self.cur, nomor)
        if hasil is not True:
            messagebox.showerror("Gagal rename", hasil)
            return
        self.segarkan_ringkas()
        self.ke_berikutnya_belum()

    def rename_hijau(self):
        idx = [i for i, it in enumerate(self.items) if it["status"] == "OK"]
        if not idx:
            messagebox.showinfo("Info", "Tidak ada file hijau.")
            return
        if not messagebox.askyesno(
                "Konfirmasi",
                f"Rename {len(idx)} file hijau sekarang?\n"
                "(Yang kuning dan merah tidak diubah. Masih bisa di-Undo.)"):
            return
        gagal = []
        for i in idx:
            hasil = self.lakukan_rename(i, self.items[i]["nomor"])
            if hasil is not True:
                gagal.append(f"{self.items[i]['path'].name}: {hasil}")
        self.segarkan_ringkas()
        if gagal:
            messagebox.showwarning("Sebagian gagal", "\n".join(gagal[:15]))
        sisa = next((k for k, it in enumerate(self.items)
                     if it["status"] != "SUDAH"), None)
        if sisa is not None:
            self.pilih(sisa)

    def undo(self):
        if not self.undo_stack:
            return
        i, lama, baru, snapshot = self.undo_stack.pop()
        try:
            if lama.exists():
                raise FileExistsError(f"{lama.name} sudah ada.")
            baru.rename(lama)
        except Exception as e:
            messagebox.showerror("Undo gagal", str(e))
            return
        self.items[i] = snapshot
        self.segarkan_baris(i)
        self.segarkan_ringkas()
        self.pilih(i)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()