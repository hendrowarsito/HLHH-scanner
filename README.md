# HLHH-scanner
# 📈 Screener Higher High / Higher Low

Aplikasi Streamlit untuk menyaring saham & crypto yang membentuk struktur uptrend (minimal N Higher High + N Higher Low), sesuai aturan Dow: **HL baru tidak boleh ≤ HL sebelumnya.**

> ⚠️ **Bukan financial advice.** Alat *screening* — menjawab "apa yang layak dilihat", bukan "apa yang layak dibeli".

---

## 📁 Isi

| File | Fungsi |
|---|---|
| `app.py` | UI Streamlit |
| `hhhl_detector.py` | Mesin deteksi swing + segmentasi struktur |
| `data_sources.py` | Konektor yfinance & OKX |
| `tickers.xlsx` | **Daftar instrumen — kamu isi sendiri** |
| `requirements.txt` | Dependensi |

---

## 🚀 Deploy ke Streamlit Cloud

1. Buat repo GitHub baru, upload **kelima file** di atas ke root repo.
2. Buka [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Pilih repo, branch `main`, main file path: `app.py`.
4. Klik **Deploy**. Build pertama ~2–3 menit.

Tidak perlu API key. OKX memakai endpoint publik, yfinance tidak butuh autentikasi.

### Jalankan lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 📄 Mengisi `tickers.xlsx`

| Kolom | Wajib | Isi |
|---|---|---|
| **Ticker** | ✅ | Saham IDX: `BBCA.JK` (**wajib sufiks .JK**) · Saham US: `NVDA` · Crypto: `BTC-USDT-SWAP` |
| **Source** | ✅ | `yfinance` atau `okx` (ada dropdown) |
| Nama | — | Label bebas |
| Kategori | — | `Saham Indo` · `Saham US` · `Crypto`. Kosongkan → ditebak otomatis |
| Aktif | — | `TRUE`/`FALSE` — matikan baris tanpa menghapusnya |
| Catatan | — | Tidak dibaca aplikasi |

**Kategori** dipakai untuk memfilter instrumen sebelum scan (multiselect di sidebar) dan
tampil sebagai kolom di tabel hasil. Kalau selnya kosong, kategori ditebak:
`.JK` → Saham Indo · source `okx` / kode `-USDT-SWAP` → Crypto · sisanya → Saham US.

Dua cara memakai:
- **Edit `tickers.xlsx` di repo** → jadi daftar bawaan, ikut ter-deploy
- **Upload lewat sidebar** → menimpa daftar bawaan untuk sesi itu saja

💡 Tombol **"Muat daftar perp USDT"** di sidebar menampilkan seluruh kode instrumen OKX yang valid, supaya kamu tidak salah ketik.

---

## ⚙️ Parameter

| Parameter | Default | Arti |
|---|---|---|
| Timeframe | 1D | 4H hanya penuh di OKX; yfinance memakai 1H (Yahoo batasi ~180 hari) |
| Lookback | 90 bar | Terlalu pendek = struktur tak terbentuk; terlalu panjang = struktur usang |
| Min HH / HL | 2 / 2 | Syarat lolos |
| **Sensitivitas (k × ATR)** | 1,5 | **Parameter paling berpengaruh.** Kecil = lebih banyak swing |
| Toleransi HL | 0% | Kelonggaran noise wick. 0,5% menyaring noise tanpa melonggarkan pelanggaran nyata |
| Hitung swing tentatif | ❌ off | ⚠️ Lihat peringatan di bawah |
| LH membatalkan struktur | ❌ off | Default: hanya pelanggaran HL yang membatalkan (Dow) |
| Hanya struktur belum pernah patah | ❌ off | Buang instrumen dengan riwayat pelanggaran HL |

---

## ⚠️ DUA HAL YANG WAJIB DIPAHAMI

### 1. Swing tentatif dan look-ahead bias

Titik harga baru menjadi *swing high* setelah harga berbalik turun sejauh threshold. Selama harga masih di puncak, ia hanya "tertinggi sejauh ini" — **bukan** swing high.

| Mode | Kapan dipakai |
|---|---|
| **Tentatif OFF** (default) | Backtest & keputusan. Hanya swing terkonfirmasi |
| Tentatif ON | Watchlist "hampir memenuhi" saja |

🔴 **Jangan pernah backtest dengan tentatif ON** — kamu memakai informasi masa depan untuk menentukan swing masa lalu. Hasilnya akan tampak jauh lebih bagus dari kenyataan.

Konsekuensi praktis: dengan default ketat, **lebih sedikit instrumen lolos**. Itu memang tujuannya.

### 2. Struktur patah → segmentasi

Pelanggaran HL tidak membuang instrumen selamanya — ia memulai **segmen baru**. HH/HL dihitung **hanya dari segmen aktif**, dengan penalti skor ×0,85 per pelanggaran.

Kalau kamu mau aturan paling murni (sekali patah = buang), centang **"Hanya struktur yang belum pernah patah"**.

**Equal low dihitung sebagai pelanggaran** — HL harus lebih *tinggi*, bukan sama.

---

## 📊 Membaca hasil

Hasil dibagi 4 tampilan: **Lolos · Semua · Detail · Error**.
Di tampilan **Semua**, klik satu baris → chart instrumen itu langsung terbuka di **Detail**.

| Kolom | Arti |
|---|---|
| **Kategori** | Saham Indo 🇮🇩 · Saham US 🇺🇸 · Crypto 🪙 |
| **Grade** | A+ ≥85 · A ≥70 · B ≥55 · C ≥40 · D <40 |
| **Invalidasi (HL)** | HL terkonfirmasi terakhir = **level struktur patah**. Bisa dipakai sebagai anchor SL struktural |
| **Jarak ke inval %** | Seberapa jauh harga dari level itu. Negatif = struktur sudah patah |
| **LH warn** | Lower High di segmen aktif — momentum melemah, belum batal |
| **Patah** | Berapa kali struktur pernah dilanggar sepanjang lookback |
| **Threshold %** | Ambang ZigZag yang dihitung otomatis dari ATR instrumen itu |

---

## 🔬 Protokol validasi — jangan lewati

Aplikasi ini menghasilkan daftar. **Daftar itu belum berarti apa-apa sampai diuji.**

| # | Pertanyaan | n minimum |
|---|---|---|
| 1 | Apakah instrumen lolos outperform kontrol acak (return 20 bar ke depan)? | 50/grup |
| 2 | Apakah Grade A benar lebih baik dari Grade C? | 30/grade |
| 3 | Berapa base rate struktur patah dalam 20 bar? | 50 |

### 🔴 Kriteria buang — tulis sekarang, sebelum terikat

> Kalau selisih return grup lolos vs kontrol acak **< 2% pada n≥50**, screener ini tidak menambah edge. Gunakan hanya sebagai penyaring visual, bukan dasar keputusan.

**Karena itu: unduh CSV setiap kali scan.** Streamlit Cloud bersifat ephemeral — tidak ada yang tersimpan otomatis. Tanpa log bertanggal, ketiga pertanyaan di atas tidak akan pernah bisa dijawab.

---

## 🩺 Troubleshooting

| Gejala | Penyebab |
|---|---|
| Saham IDX "Tidak ada data" | Kurang sufiks `.JK` |
| Crypto "OKX error" | Format salah — pakai `BTC-USDT-SWAP`, cek lewat tombol daftar perp |
| yfinance lambat/gagal massal | Rate limit Yahoo. Tunggu beberapa menit, atau kurangi jumlah ticker |
| Semua instrumen tidak lolos | Turunkan k×ATR ke 1,0, perpanjang lookback, atau aktifkan swing tentatif (watchlist saja) |
| Scan timeout | Terlalu banyak ticker. yfinance jauh lebih lambat dari OKX — pecah jadi beberapa file |

---

## 📌 Posisi dalam sistem trading

```
LAPIS 1 — SCREENING (aplikasi ini)   → "apa yang layak dilihat?"
LAPIS 2 — KONTEKS (Fib/EW/Harmonic)  → "zona mana yang penting?"
LAPIS 3 — TRIGGER (checklist)        → "kapan masuk?"
LAPIS 4 — EKSEKUSI                   → SL, R:R, size
```

⚠️ Screener **tidak pernah** menjadi trigger entry.

---

*v1.0 — Semua klaim performa BELUM DIVALIDASI sampai protokol di atas dijalankan. Bukan financial advice.*