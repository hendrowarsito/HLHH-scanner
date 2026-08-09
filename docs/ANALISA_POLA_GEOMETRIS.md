# Analisa Kelayakan — Deteksi Pola Geometris (Triangle, Wedge, Channel, dll)

> Pertanyaan: **bisakah program ini merangkai swing menjadi garis sehingga terbentuk
> pola seperti triangle, wedge, falling wedge, channel?**
>
> Jawaban singkat: **Bisa, dan pondasinya sudah ada.** Yang dibutuhkan bukan mesin baru,
> melainkan satu lapis di atas `detect_swings()` yang sudah jalan. Tapi ada satu
> keputusan teknis yang menentukan hidup-matinya fitur ini — dan pilihan yang "paling
> masuk akal" ternyata yang salah. Lihat bagian 3.

---

## 1. Kenapa pondasinya sudah ada

Sebuah pola geometris pada dasarnya = **dua garis** + **aturan hubungan antar garis**.
Untuk menggambar dua garis, yang dibutuhkan hanyalah titik-titik pivot — dan itu sudah
diproduksi mesin yang sekarang:

| Yang dibutuhkan | Sudah tersedia di kode |
|---|---|
| Titik pivot high/low | `detect_swings()` → `Swing(idx, price, kind)` (`hhhl_detector.py:100`) |
| Sumbu-x yang seragam | `Swing.idx` = indeks bar, sudah bebas dari lubang akhir pekan |
| Ambang adaptif per instrumen | `adaptive_threshold()` berbasis ATR (`hhhl_detector.py:86`) |
| Kanvas untuk menggambar garis | Chart Plotly di tab Detail sudah menggambar segmen aktif (`app.py`) |
| Data wick (bukan cuma close) | `data_sources.fetch()` sudah mengembalikan `high` & `low` |

Artinya beban kerjanya adalah **satu modul baru** (`pattern_detector.py`) yang menerima
`List[Swing]` dan mengembalikan dua garis + nama pola. Tidak ada perombakan arsitektur.

---

## 2. Algoritma yang diusulkan

```
1. Ambil swing dari detect_swings()  →  pisahkan jadi titik H dan titik L
2. Cocokkan GARIS ATAS pada titik H, GARIS BAWAH pada titik L   ← bagian kritis, lihat §3
3. Ukur tiga angka:
      slope_atas, slope_bawah          (dalam ruang log-harga, per bar)
      rasio = lebar_akhir / lebar_awal (menyempit / melebar / sejajar)
4. Klasifikasi dari kombinasi ketiganya
```

Tabel klasifikasinya deterministik — tidak ada tebak-tebakan:

| Pola | slope atas | slope bawah | rasio lebar |
|---|---|---|---|
| **Symmetrical triangle** | turun | naik | menyempit (<0,75) |
| **Ascending triangle** | ±datar | naik | menyempit |
| **Descending triangle** | turun | ±datar | menyempit |
| **Rising wedge** | naik | naik lebih curam | menyempit |
| **Falling wedge** | turun lebih curam | turun | menyempit |
| **Ascending / Descending channel** | naik / turun | sejajar | ±tetap (0,75–1,3) |
| **Rectangle (range)** | ±datar | ±datar | ±tetap |
| **Broadening** | naik | turun | melebar (>1,3) |

Catatan penting: **"datar" harus diukur relatif terhadap tinggi pola**, bukan sebagai
angka mutlak %. Garis 0,05%/bar itu datar untuk BTC, tapi curam untuk saham yang
bergerak 0,2% sehari. Rumus yang dipakai: `gerak_garis_sepanjang_jendela / lebar_awal_pola`.

---

## 3. Temuan utama — regresi vs garis singgung

Refleks pertama adalah memasang **regresi least-squares** menembus titik-titik swing.
Itu keliru, dan efeknya besar. Trendline yang benar harus **menyinggung** ekstrem
(semua harga di bawah garis atas, di atas garis bawah), sementara regresi menarik garis
ke *rata-rata* titik — sehingga kemiringannya bias dan pola berubah identitas.

Hasil uji pada 72 kasus (8 bentuk × 3 level noise × 3 seed), memakai `detect_swings()`
yang asli:

| Metode fitting | Akurasi klasifikasi |
|---|---|
| Regresi least-squares | **45 / 72 (62%)** |
| **Garis singgung (tangent/hull)** | **68 / 72 (94%)** |

Rincian kegagalan regresi — bukan meleset acak, tapi **salah nama pola secara sistematis**:

| Bentuk sebenarnya | Dibaca regresi sebagai | Konsisten salah |
|---|---|---|
| Symmetrical triangle | Descending triangle | 9/9 |
| Descending triangle | Falling wedge | 9/9 |
| Rectangle (range) | Descending channel | 9/9 |

Dengan garis singgung, ketiganya benar 9/9. Sisa 4 kegagalan ada di channel yang
sesekali terbaca "Broadening" saat noise menekan salah satu ekstrem keluar jalur —
bisa diperbaiki dengan memaksa garis bawah **sejajar** garis atas khusus untuk kandidat
channel (regression channel), atau melonggarkan ambang divergensi.

**Kesimpulan bagian ini:** fitur ini layak dibangun, asalkan sejak awal memakai
pencocokan garis singgung. Kalau memakai regresi, hasilnya akan terlihat "jalan" di
layar tapi memberi nama pola yang salah pada tiga bentuk paling umum.

---

## 4. Yang perlu disesuaikan di kode yang ada

### a. `floor=2.0` pada `adaptive_threshold()` membatasi jumlah swing

Pola butuh lebih banyak pivot daripada screening HH/HL. Syarat klasik satu trendline
adalah **3 sentuhan**, jadi minimal ~6 swing (3 H + 3 L). Padahal:

```
k=1.5  th=2.00%  swing=10     k=0.8  th=2.00%  swing=10
k=1.2  th=2.00%  swing=10     k=0.6  th=2.00%  swing=10
k=1.0  th=2.00%  swing=10     k=0.4  th=2.00%  swing=10
```

Menurunkan k **tidak menambah swing sama sekali** begitu `k × ATR%` jatuh di bawah
lantai 2%. Untuk instrumen tenang, slider Sensitivitas praktis mati. Kalau deteksi pola
butuh pivot lebih halus, lantai ini harus bisa diturunkan (parameter terpisah untuk
modul pola, jangan mengubah perilaku screener yang sudah ada).

### b. Swing dihitung dari harga *close*, garis pola idealnya dari *wick*

`analyze_structure()` memanggil `detect_swings(prices)` dengan `prices = closes`;
`high`/`low` hanya dipakai menghitung ATR. Trendline konvensional digambar menyentuh
wick. Ini tinggal mengambil `highs[s.idx]` dan `lows[s.idx]` saat memasang garis —
tanpa mengubah cara swing dideteksi. Uji sintetis di sini **tidak bisa membuktikan**
mana yang lebih baik (wick sintetisnya cuma close ± konstanta, hasilnya identik 68/72);
ini perlu dinilai ulang dengan data nyata.

### c. Fitting harus di ruang log-harga

Wedge dan channel adalah pernyataan tentang *persentase*, bukan rupiah. Pada rentang
harga lebar, garis lurus di skala linier menjadi melengkung di skala log dan sebaliknya.
Prototipe ini sudah memakai `log(price)` dan itu sebaiknya dipertahankan.

---

## 5. Batasan yang harus disadari sebelum membangun

1. **Repainting.** Sama seperti swing tentatif yang sudah diperingatkan di README:
   pola yang terlihat hari ini bisa berubah bentuk besok saat swing terakhir bergeser.
   Segitiga bisa berubah jadi wedge tanpa satu bar pun direvisi. Konsekuensinya —
   **jangan pernah backtest dengan pola yang memakai swing tentatif.**
2. **Dengan 2 titik, garis apa pun selalu bisa ditarik.** Dua titik H + dua titik L
   *selalu* menghasilkan "pola". Tanpa syarat minimum sentuhan, fitur ini akan
   memberi nama pola pada apa saja, termasuk noise. Wajib ada gerbang: minimal 3
   sentuhan per garis, minimal ~15–20 bar durasi, dan residu maksimum.
3. **Kelas pola tidak saling eksklusif.** Rising wedge dan ascending channel hanya
   dibedakan oleh seberapa cepat menyempit; batas 0,75 itu pilihan, bukan hukum alam.
   Angka batas harus dikalibrasi, dan sampai dikalibrasi, hasilnya adalah dugaan.
4. **Uji ini sintetis, bukan pasar nyata.** Jaringan ke OKX diblokir dari lingkungan
   ini (proxy 403), jadi klaim 94% berlaku untuk bentuk buatan yang bersih. Pada data
   nyata angkanya pasti lebih rendah — pola nyata jarang serapi definisinya.
5. **Nilai prediktifnya belum diketahui.** Ini yang paling penting. Menggambar segitiga
   itu masalah geometri dan sudah selesai di atas. Apakah segitiga itu memprediksi
   sesuatu adalah pertanyaan yang sama sekali berbeda, dan literatur akademik soal ini
   jauh dari sepakat.

---

## 6. Rancangan integrasi

**File baru `pattern_detector.py`** (tidak menyentuh `hhhl_detector.py`):

```python
@dataclass
class Pattern:
    name: str                 # "Falling wedge", "Ascending triangle", ...
    upper: Tuple[float, float]   # (slope, intercept) di ruang log
    lower: Tuple[float, float]
    touches_upper: int
    touches_lower: int
    width_ratio: float        # <1 menyempit, >1 melebar
    start_idx: int
    end_idx: int
    apex_idx: Optional[int]   # perpotongan garis, kalau menyempit
    quality: float            # 0-1: sentuhan, residu, durasi
    tentative: bool           # memakai swing yang belum terkonfirmasi

def detect_pattern(swings, highs, lows, min_touches=3) -> Optional[Pattern]
```

**Di `app.py`** — dua sentuhan kecil:
- Tab Detail: `fig.add_trace()` dua garis pola (garis putus-putus, warna berbeda dari
  segmen aktif), diperpanjang ke kanan sampai apex.
- Tabel hasil: kolom **Pola** + **Kualitas pola**, ikut ke CSV.

**Estimasi:** modul + uji ±250 baris, integrasi UI ±40 baris. Bagian yang memakan waktu
bukan kodenya, melainkan kalibrasi ambang (§5 poin 3) dan validasi (§7).

---

## 7. Protokol validasi — jangan dilewati

Selaras dengan disiplin yang sudah ditulis di README, sebelum pola dipakai sebagai dasar
keputusan apa pun:

| # | Pertanyaan | n minimum |
|---|---|---|
| 1 | Apakah pola yang terdeteksi disepakati mata manusia? (label manual buta) | 50 pola |
| 2 | Berapa sering pola berubah nama sebelum selesai (repaint rate)? | 100 pola |
| 3 | Apakah return 20 bar setelah pola beda dari kontrol acak? | 50/jenis pola |

### 🔴 Kriteria buang — tulis sekarang, sebelum terikat

> Kalau **repaint rate > 40%**, pola tidak layak dipakai untuk keputusan apa pun —
> hanya boleh jadi anotasi visual pada chart, tanpa kolom skor dan tanpa klaim.

---

## 8. Rekomendasi bertahap

| Fase | Isi | Risiko |
|---|---|---|
| **1. Visual saja** | Gambar dua garis di tab Detail, tanpa nama pola, tanpa skor | Rendah — hanya membantu mata |
| **2. Penamaan** | Tambah kolom Pola + kualitas, setelah ambang dikalibrasi | Sedang — nama yang salah menyesatkan |
| **3. Skoring** | Pola ikut memengaruhi Grade | **Tinggi — jangan sebelum §7 dijalankan** |

Fase 1 sudah memberi sebagian besar manfaatnya: mata jauh lebih cepat menangkap struktur
kalau garisnya sudah tergambar, dan tidak ada klaim yang bisa salah. Saran saya berhenti
di Fase 1 dulu, pakai beberapa minggu, baru putuskan apakah Fase 2 layak.

---

*Analisa ini berbasis prototipe yang dijalankan terhadap `detect_swings()` yang asli.
Angka 62% vs 94% berasal dari 72 kasus sintetis, bukan data pasar. Bukan financial advice.*
