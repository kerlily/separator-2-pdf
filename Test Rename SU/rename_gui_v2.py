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
BATAS_ATAS = 100000
LEBAR_MAKS_USULAN = 200  # usulan dari teks OCR hanya jika rentang sesempit ini


def tebak_nomor(path):
    """Return (nomor, catatan). nomor None = tidak yakin."""
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


def token_angka(path):
    """Semua token 5 karakter mirip angka di halaman 1 (sudah dikoreksi)."""
    try:
        with fitz.open(path) as d:
            teks = d[0].get_text("text")
    except Exception:
        return []
    datar = re.sub(r"\s+", " ", teks)
    hasil = []
    for m in re.finditer(r"(?<![0-9])[0-9OoIl|!]{5}(?![0-9])", datar):
        mentah = m.group(0)
        if sum(c.isdigit() for c in mentah) >= 2:
            hasil.append(mentah.translate(KOREKSI))
    return list(dict.fromkeys(hasil))


def varian_satu_digit(nomor):
    out = set()
    for p in range(5):
        for d in "0123456789":
            if d != nomor[p]:
                out.add(nomor[:p] + d + nomor[p + 1:])
    return out


def lis_indeks(angka):
    """Indeks anggota urutan naik (strict) terpanjang."""
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
    return aman


# ==========================================
# APLIKASI
# ==========================================
LABEL = {"OK": "✔ OK", "CEK": "? CEK", "USUL": "~ USUL",
         "MANUAL": "✖ MANUAL", "SUDAH": "• SUDAH"}


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"Renaming surat ukur josjis — {NAMA_DESA} {TAHUN}")
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
        self.tree.column("nomor", width=70, anchor="center")
        self.tree.column("status", width=80, anchor="center")
        sb = ttk.Scrollbar(kiri, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("OK", background="#d6f5d6")
        self.tree.tag_configure("CEK", background="#fff3b0")
        self.tree.tag_configure("USUL", background="#ffe0b3")
        self.tree.tag_configure("MANUAL", background="#ffd0d0")
        self.tree.tag_configure("SUDAH", background="#e3e3e3", foreground="#777")
        self.tree.bind("<<TreeviewSelect>>", self.saat_pilih)

        self.lbl_file = ttk.Label(kanan, text="", font=("Segoe UI", 12, "bold"),
                                  padding=(8, 6))
        self.lbl_file.pack(fill="x")
        self.lbl_catatan = tk.Label(kanan, text="", anchor="w", justify="left",
                                    font=("Segoe UI", 10), padx=8,
                                    wraplength=900)
        self.lbl_catatan.pack(fill="x")
        self.lbl_tetangga = ttk.Label(kanan, text="", padding=(8, 2))
        self.lbl_tetangga.pack(fill="x")

        self.gambar = tk.Label(kanan, bg="#888")
        self.gambar.pack(fill="both", expand=True, padx=8, pady=6)

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

        def baru(p, nomor, cat, status, urut):
            return {"path": p, "nomor": nomor, "catatan": cat,
                    "status": status, "urut": urut, "lompat": False,
                    "rentang": None, "usulan": None, "info": ""}

        for i, p in enumerate(pdfs, 1):
            self.root.title(f"Membaca {i}/{len(pdfs)} ...")
            self.root.update_idletasks()
            m = POLA_SUDAH.match(p.name)
            if m:
                # sudah ter-rename sebelum program dibuka: posisi urutan
                # aslinya tidak diketahui, jadi tidak dipakai sebagai patokan
                self.items.append(baru(p, m.group(1), [], "SUDAH", False))
                continue
            nomor, cat = tebak_nomor(p)
            if nomor is None:
                self.items.append(baru(p, None, cat, "MANUAL", True))
            else:
                self.items.append(baru(p, nomor, cat,
                                       "CEK" if cat else "OK", True))

        # nomor dobel
        sudah = {it["nomor"] for it in self.items if it["status"] == "SUDAH"}
        hitung = Counter(it["nomor"] for it in self.items
                         if it["status"] in ("OK", "CEK"))
        for it in self.items:
            if it["status"] in ("OK", "CEK") and (
                    hitung[it["nomor"]] > 1 or it["nomor"] in sudah):
                it["catatan"].append("nomor dobel / sudah dipakai file lain")
                it["status"] = "CEK"

        self.tandai_pelanggar_urutan()
        self.hitung_rentang()

        self.root.title(f"Rename Surat Ukur — {NAMA_DESA} {TAHUN}")
        for i in range(len(self.items)):
            self.tree.insert("", "end", iid=str(i), values=("", "", ""))
        self.segarkan_semua()

        awal = next((i for i, it in enumerate(self.items)
                     if it["status"] != "SUDAH"), 0)
        self.pilih(awal)

    # ---------- LOGIKA URUTAN ----------
    def tandai_pelanggar_urutan(self):
        """Nomor yang keluar dari urutan naik terpanjang = dicurigai salah baca."""
        pos = [i for i, it in enumerate(self.items)
               if it["urut"] and it["nomor"]]
        angka = [int(self.items[i]["nomor"]) for i in pos]
        aman = {pos[k] for k in lis_indeks(angka)}
        for i in pos:
            if i not in aman:
                it = self.items[i]
                it["lompat"] = True
                it["catatan"].append(
                    "nomor melanggar urutan file (kemungkinan salah baca)")
                if it["status"] == "OK":
                    it["status"] = "CEK"

    def hitung_rentang(self):
        """Rentang valid + usulan untuk file yang nomornya belum pasti."""
        lo, grup = 0, []
        for i, it in enumerate(self.items):
            if not it["urut"]:
                continue
            if it["nomor"] and not it["lompat"]:
                self._proses_grup(grup, lo, int(it["nomor"]))
                lo, grup = int(it["nomor"]), []
            else:
                grup.append(i)
        self._proses_grup(grup, lo, BATAS_ATAS)

        for it in self.items:
            if it["status"] in ("MANUAL", "USUL"):
                it["status"] = "USUL" if it["usulan"] else "MANUAL"

    def _proses_grup(self, grup, lo, hi):
        k = len(grup)
        for j, idx in enumerate(grup, 1):
            it = self.items[idx]
            mn, mx = lo + j, hi - (k - j + 1)
            it["usulan"], it["info"] = None, ""
            if mx < mn:
                it["rentang"] = None
                it["info"] = ("urutan tidak konsisten (kemungkinan ada "
                              "nomor tetangga yang salah)")
                continue
            it["rentang"] = (mn, mx)
            if mn == mx:
                it["usulan"] = f"{mn:05d}"
                it["info"] = "hanya angka ini yang cocok dengan urutan"
                continue
            if mx - mn > LEBAR_MAKS_USULAN:
                continue
            if "token" not in it:
                it["token"] = token_angka(it["path"])
            kand = [t for t in it["token"] if mn <= int(t) <= mx]
            if len(kand) == 1:
                it["usulan"] = kand[0]
                it["info"] = ("satu-satunya angka di teks OCR "
                              "yang masuk rentang urutan")
            elif not kand and it["nomor"]:
                var = [v for v in varian_satu_digit(it["nomor"])
                       if mn <= int(v) <= mx]
                if len(var) == 1:
                    it["usulan"] = var[0]
                    it["info"] = (f"perbaikan 1 digit dari tebakan OCR "
                                  f"({it['nomor']}) agar sesuai urutan")

    def teks_rentang(self, it):
        if not it["rentang"]:
            return ""
        mn, mx = it["rentang"]
        if mx - mn > 5000:
            return f"Rentang valid dari urutan: ≥ {mn:05d}"
        return f"Rentang valid dari urutan: {mn:05d} – {mx:05d}"

    # ---------- TAMPILAN BARIS ----------
    def segarkan_baris(self, i):
        it = self.items[i]
        if it["nomor"] and not (it["status"] in ("USUL",)):
            tampil = it["nomor"]
            if it["lompat"] and it["usulan"]:
                tampil = f"{it['nomor']}→{it['usulan']}"
        elif it["usulan"]:
            tampil = "~" + it["usulan"]
        else:
            tampil = ""
        self.tree.item(str(i), values=(it["path"].name, tampil,
                                       LABEL[it["status"]]),
                       tags=(it["status"],))

    def segarkan_ringkas(self):
        c = Counter(it["status"] for it in self.items)
        self.lbl_ringkas.config(
            text=f"Total {len(self.items)} | OK {c['OK']} | CEK {c['CEK']}"
                 f" | USUL {c['USUL']} | MANUAL {c['MANUAL']}"
                 f" | SUDAH {c['SUDAH']}")

    def segarkan_semua(self):
        for i in range(len(self.items)):
            self.segarkan_baris(i)
        self.segarkan_ringkas()

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
        self.var.set(it["usulan"] or it["nomor"] or "")
        self.lbl_file.config(text=it["path"].name)

        warna = {"OK": "#1b7a1b", "CEK": "#9a6b00", "USUL": "#a05a00",
                 "MANUAL": "#b00020", "SUDAH": "#666"}[it["status"]]
        baris = []
        if it["catatan"]:
            baris.append("⚠ " + "; ".join(it["catatan"]))
        if it["usulan"]:
            baris.append(f"Usulan {it['usulan']}: {it['info']}")
        elif it["info"]:
            baris.append(it["info"])
        if not baris:
            baris.append({"OK": "Tebakan OCR yakin — cocokkan dengan gambar.",
                          "SUDAH": "File ini sudah ter-rename.",
                          "MANUAL": "OCR gagal — baca dari gambar."}
                         .get(it["status"], ""))
        self.lbl_catatan.config(text="\n".join(baris), fg=warna)

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
                it = self.items[j]
                if it["urut"] and it["nomor"] and not it["lompat"]:
                    return it["nomor"]
            return "?"
        sebelum = cari(range(i - 1, -1, -1))
        sesudah = cari(range(i + 1, len(self.items)))
        teks = f"Tetangga: sebelumnya {sebelum} | berikutnya {sesudah}"
        r = self.teks_rentang(self.items[i])
        return f"{teks}   |   {r}" if r else teks

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
        snapshot = dict(it, catatan=list(it["catatan"]))
        self.undo_stack.append((i, lama, baru, snapshot))
        it["path"] = baru
        it["nomor"] = nomor
        it["catatan"] = []
        it["status"] = "SUDAH"
        it["lompat"] = False   # sudah dikonfirmasi manual -> jadi patokan
        it["usulan"], it["info"], it["rentang"] = None, "", None
        return True

    def rename_sekarang(self):
        if self.cur is None:
            return
        nomor = self.var.get().strip()
        if not re.fullmatch(r"\d{5}", nomor):
            messagebox.showwarning("Nomor salah",
                                   "Nomor harus tepat 5 digit angka.")
            return
        hasil = self.lakukan_rename(self.cur, nomor)
        if hasil is not True:
            messagebox.showerror("Gagal rename", hasil)
            return
        self.hitung_rentang()
        self.segarkan_semua()
        self.ke_berikutnya_belum()

    def rename_hijau(self):
        idx = [i for i, it in enumerate(self.items) if it["status"] == "OK"]
        if not idx:
            messagebox.showinfo("Info", "Tidak ada file hijau.")
            return
        if not messagebox.askyesno(
                "Konfirmasi",
                f"Rename {len(idx)} file hijau sekarang?\n"
                "(Yang lain tidak diubah. Masih bisa di-Undo.)"):
            return
        gagal = []
        for i in idx:
            hasil = self.lakukan_rename(i, self.items[i]["nomor"])
            if hasil is not True:
                gagal.append(f"{self.items[i]['path'].name}: {hasil}")
        self.hitung_rentang()
        self.segarkan_semua()
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
        self.hitung_rentang()
        self.segarkan_semua()
        self.pilih(i)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()