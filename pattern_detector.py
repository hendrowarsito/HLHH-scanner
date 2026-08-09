"""
pattern_detector.py — Deteksi pola geometris dari swing HH/HL
Triangle · Wedge · Channel · Rectangle · Broadening

BUKAN FINANCIAL ADVICE. Ini anotasi visual, bukan sinyal.

Prinsip desain (lihat docs/ANALISA_POLA_GEOMETRIS.md):
1. Garis dicocokkan dengan cara MENYINGGUNG ekstrem, bukan regresi least-squares.
   Regresi menarik garis ke rata-rata titik sehingga kemiringannya bias — pada uji
   sintetis ia salah membaca symmetrical triangle, descending triangle, dan
   rectangle secara sistematis (45/72 benar vs 68/72 untuk garis singgung).
2. Fitting dilakukan di ruang log-harga, karena wedge/channel adalah pernyataan
   tentang persentase, bukan rupiah.
3. "Datar" diukur relatif terhadap tinggi pola, bukan sebagai angka mutlak %.
4. Pola dengan sentuhan kurang dari syarat TIDAK diberi nama. Dua titik selalu
   bisa dilewati sebuah garis — tanpa gerbang ini, noise pun akan dinamai pola.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
import itertools
import math


# ─────────────────────────────────────────────────────────────
# STRUKTUR DATA
# ─────────────────────────────────────────────────────────────

@dataclass
class Line:
    slope: float          # per bar, di ruang log-harga
    intercept: float      # di ruang log-harga
    touches: int          # titik yang menempel garis (dalam toleransi)

    def at(self, x: float) -> float:
        """Harga garis pada bar ke-x (dikembalikan ke ruang harga biasa)."""
        return math.exp(self.slope * x + self.intercept)


@dataclass
class Pattern:
    name: str = "-"
    upper: Optional[Line] = None
    lower: Optional[Line] = None
    start_idx: int = 0
    end_idx: int = 0
    width_ratio: float = 1.0          # <1 menyempit, >1 melebar
    apex_idx: Optional[int] = None    # perpotongan garis, kalau menyempit
    quality: float = 0.0              # 0-1
    tentative: bool = False           # memakai swing yang belum terkonfirmasi
    notes: List[str] = field(default_factory=list)

    @property
    def bars(self) -> int:
        return self.end_idx - self.start_idx


# nama pola yang menyempit — dipakai untuk memutuskan perlu apex atau tidak
CONVERGING = {"Symmetrical triangle", "Ascending triangle", "Descending triangle",
              "Rising wedge", "Falling wedge"}


# ─────────────────────────────────────────────────────────────
# 1. PENCOCOKAN GARIS SINGGUNG
# ─────────────────────────────────────────────────────────────

def fit_tangent(points: Sequence[Tuple[int, float]], side: str,
                tol_pct: float = 0.5, touch_pct: float = 1.0) -> Optional[Line]:
    """
    Cari garis yang MENYINGGUNG titik-titik ekstrem.

    side="up"   : semua titik harus berada di bawah garis (garis atas / resistance)
    side="down" : semua titik harus berada di atas garis (garis bawah / support)

    tol_pct   : seberapa jauh sebuah titik boleh menembus garis tanpa
                mendiskualifikasi garis itu (meredam noise wick)
    touch_pct : jarak maksimum agar sebuah titik dihitung "menyentuh"

    Dipilih garis dengan sentuhan terbanyak; seri dipecah oleh jarak total terkecil.
    """
    if len(points) < 2:
        return None

    pts = [(x, math.log(p)) for x, p in points if p > 0]
    if len(pts) < 2:
        return None

    tol = tol_pct / 100.0
    touch = touch_pct / 100.0
    best = None

    for (x1, y1), (x2, y2) in itertools.combinations(pts, 2):
        if x2 == x1:
            continue
        slope = (y2 - y1) / (x2 - x1)
        intercept = y1 - slope * x1
        resid = [y - (slope * x + intercept) for x, y in pts]

        # garis tidak boleh dilewati titik di sisi yang salah
        if side == "up" and max(resid) > tol:
            continue
        if side == "down" and min(resid) < -tol:
            continue

        touches = sum(1 for r in resid if abs(r) <= touch)
        gap = sum(abs(r) for r in resid)
        cand = (touches, -gap, slope, intercept)
        if best is None or cand > best:
            best = cand

    if best is None:
        return None
    touches, _, slope, intercept = best
    return Line(slope=slope, intercept=intercept, touches=touches)


# ─────────────────────────────────────────────────────────────
# 2. KLASIFIKASI
# ─────────────────────────────────────────────────────────────

def classify(upper: Line, lower: Line, start: int, end: int,
             flat_frac: float = 0.15,
             converge: float = 0.75, diverge: float = 1.3) -> Tuple[str, float]:
    """
    Beri nama pola dari kemiringan kedua garis + perubahan lebarnya.

    flat_frac: sebuah garis disebut "datar" kalau total geraknya sepanjang jendela
               kurang dari sekian bagian dari tinggi pola di awal. Ini yang membuat
               ambang datar ikut menyesuaikan volatilitas instrumen.
    """
    w0 = (upper.slope * start + upper.intercept) - (lower.slope * start + lower.intercept)
    w1 = (upper.slope * end + upper.intercept) - (lower.slope * end + lower.intercept)
    if w0 <= 0:
        return "-", 1.0

    ratio = w1 / w0
    span = max(1, end - start)
    # gerak tiap garis sepanjang jendela, relatif tinggi pola
    mu = upper.slope * span / w0
    ml = lower.slope * span / w0
    flat_u, flat_l = abs(mu) < flat_frac, abs(ml) < flat_frac

    if ratio < converge:
        if flat_u and ml > 0:
            return "Ascending triangle", ratio
        if flat_l and mu < 0:
            return "Descending triangle", ratio
        if mu < 0 and ml > 0:
            return "Symmetrical triangle", ratio
        if mu > 0 and ml > 0:
            return "Rising wedge", ratio
        if mu < 0 and ml < 0:
            return "Falling wedge", ratio
        return "Menyempit (tak terklasifikasi)", ratio

    if ratio > diverge:
        return "Broadening formation", ratio

    if mu > flat_frac and ml > flat_frac:
        return "Ascending channel", ratio
    if mu < -flat_frac and ml < -flat_frac:
        return "Descending channel", ratio
    return "Rectangle / range", ratio


# ─────────────────────────────────────────────────────────────
# 3. DETEKSI
# ─────────────────────────────────────────────────────────────

def detect_pattern(swings, highs: Sequence[float], lows: Sequence[float],
                   min_touches: int = 3, max_swings: int = 8,
                   min_bars: int = 15, use_wick: bool = True) -> Optional[Pattern]:
    """
    Rangkai swing menjadi dua garis lalu beri nama polanya.

    swings      : List[Swing] dari hhhl_detector.detect_swings()
    highs/lows  : array wick sepanjang data (indeks sejajar dengan Swing.idx)
    min_touches : syarat sentuhan per garis. 3 = aturan klasik. Turunkan ke 2
                  hanya kalau sadar bahwa 2 titik selalu bisa dilewati garis.
    max_swings  : hanya sekian swing terakhir yang dipakai — pola harus aktual
    min_bars    : pola yang terlalu pendek ditolak

    Mengembalikan None kalau syarat tidak terpenuhi (ini normal dan sering).
    """
    if not swings or len(swings) < 4:
        return None

    recent = list(swings)[-max_swings:]
    n = min(len(highs), len(lows))

    def price(s, arr):
        return arr[s.idx] if (use_wick and 0 <= s.idx < n) else s.price

    hi_pts = [(s.idx, price(s, highs)) for s in recent if s.kind == "H"]
    lo_pts = [(s.idx, price(s, lows)) for s in recent if s.kind == "L"]
    if len(hi_pts) < 2 or len(lo_pts) < 2:
        return None

    start = min(recent[0].idx, hi_pts[0][0], lo_pts[0][0])
    end = max(recent[-1].idx, hi_pts[-1][0], lo_pts[-1][0])
    if end - start < min_bars:
        return None

    upper = fit_tangent(hi_pts, "up")
    lower = fit_tangent(lo_pts, "down")
    if upper is None or lower is None:
        return None

    name, ratio = classify(upper, lower, start, end)
    if name == "-":
        return None

    pat = Pattern(name=name, upper=upper, lower=lower,
                  start_idx=start, end_idx=end, width_ratio=round(ratio, 3),
                  tentative=any(not s.confirmed for s in recent))

    # apex: perpotongan kedua garis, hanya bermakna kalau menyempit
    if name in CONVERGING and upper.slope != lower.slope:
        x = (lower.intercept - upper.intercept) / (upper.slope - lower.slope)
        if end < x < end + 3 * (end - start):
            pat.apex_idx = int(round(x))

    # kualitas: sentuhan (50%), kerapatan titik ke garis (30%), durasi (20%)
    t_score = min(1.0, (min(upper.touches, 3) + min(lower.touches, 3)) / 6)
    resid = []
    for pts, ln in ((hi_pts, upper), (lo_pts, lower)):
        for x, p in pts:
            resid.append(abs(math.log(p) - (ln.slope * x + ln.intercept)))
    w0 = (upper.slope * start + upper.intercept) - (lower.slope * start + lower.intercept)
    tight = 1.0 - min(1.0, (sum(resid) / len(resid)) / w0) if w0 > 0 else 0.0
    d_score = min(1.0, (end - start) / 40)
    pat.quality = round(0.5 * t_score + 0.3 * tight + 0.2 * d_score, 2)

    if upper.touches < min_touches or lower.touches < min_touches:
        pat.notes.append(
            f"Sentuhan kurang ({upper.touches} atas / {lower.touches} bawah, "
            f"syarat {min_touches}) — bentuk belum layak dinamai")
        pat.name = "-"
    if pat.tentative:
        pat.notes.append("Memakai swing tentatif — bentuk pola masih bisa berubah")

    return pat


# ─────────────────────────────────────────────────────────────
# UJI DENGAN POLA SINTETIS
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from hhhl_detector import detect_swings, adaptive_threshold, atr_pct

    def synth(kind, n=90, noise=0.0, seed=0):
        import random
        rnd = random.Random(seed)
        out = []
        for i in range(n):
            t = i / (n - 1)
            osc = math.sin(i / 3.5)
            if kind == "symmetrical":
                amp, mid = 0.12 * (1 - 0.9 * t), 100.0
            elif kind == "falling wedge":
                amp, mid = 0.10 * (1 - 0.85 * t), 100 * (1 - 0.35 * t)
            elif kind == "rising wedge":
                amp, mid = 0.10 * (1 - 0.85 * t), 100 * (1 + 0.35 * t)
            elif kind == "ascending channel":
                amp, mid = 0.07, 100 * (1 + 0.5 * t)
            elif kind == "descending channel":
                amp, mid = 0.07, 100 * (1 - 0.4 * t)
            elif kind == "ascending triangle":
                top, floor_ = 112.0, 88 + (112 - 88) * 0.85 * t
                mid = (top + floor_) / 2
                amp = (top - floor_) / 2 / mid
            elif kind == "descending triangle":
                bot, ceil_ = 88.0, 112 - (112 - 88) * 0.85 * t
                mid = (ceil_ + bot) / 2
                amp = (ceil_ - bot) / 2 / mid
            else:
                amp, mid = 0.08, 100.0
            v = mid * (1 + amp * osc)
            out.append(v * (1 + rnd.uniform(-noise, noise)) if noise else v)
        return out

    KINDS = ["symmetrical", "falling wedge", "rising wedge", "ascending triangle",
             "descending triangle", "ascending channel", "descending channel",
             "rectangle"]

    print("=" * 72)
    print("UJI — klasifikasi pola sintetis (3 level noise x 3 seed)")
    print("=" * 72)
    benar = total = 0
    for kind in KINDS:
        hasil = {}
        for noise in (0.0, 0.005, 0.015):
            for seed in range(3):
                closes = synth(kind, noise=noise, seed=seed)
                highs = [c * 1.004 for c in closes]
                lows = [c * 0.996 for c in closes]
                th = adaptive_threshold(atr_pct(highs, lows, closes), k=0.7)
                sw = detect_swings(closes, th)
                pat = detect_pattern(sw, highs, lows, min_touches=2)
                nm = pat.name if pat else "tak terdeteksi"
                hasil[nm] = hasil.get(nm, 0) + 1
                total += 1
                benar += kind.split()[0].lower() in nm.lower()
        print(f"  {kind:<21} {hasil}")
    print(f"\n  Akurasi: {benar}/{total}")

    print()
    print("=" * 72)
    print("UJI — gerbang sentuhan (min_touches=3) menolak bentuk lemah")
    print("=" * 72)
    closes = synth("symmetrical", noise=0.015, seed=2)
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    th = adaptive_threshold(atr_pct(highs, lows, closes), k=0.7)
    sw = detect_swings(closes, th)
    for mt in (2, 3, 4, 5):
        pat = detect_pattern(sw, highs, lows, min_touches=mt)
        print(f"  min_touches={mt} → {pat.name if pat else None:<28} "
              f"sentuh={pat.upper.touches}/{pat.lower.touches} q={pat.quality}"
              if pat else f"  min_touches={mt} → None")

    print()
    print("=" * 72)
    print("UJI — data acak TIDAK boleh dinamai pola (gerbang sentuhan bekerja)")
    print("=" * 72)
    import random
    dinamai = 0
    for seed in range(20):
        rnd = random.Random(seed)
        closes, p = [], 100.0
        for _ in range(90):
            p *= 1 + rnd.gauss(0, 0.02)
            closes.append(p)
        highs = [c * 1.004 for c in closes]
        lows = [c * 0.996 for c in closes]
        th = adaptive_threshold(atr_pct(highs, lows, closes), k=0.7)
        pat = detect_pattern(detect_swings(closes, th), highs, lows, min_touches=3)
        if pat and pat.name != "-":
            dinamai += 1
    print(f"  random walk dinamai pola: {dinamai}/20 "
          f"({'wajar' if dinamai <= 8 else 'TERLALU LONGGAR'})")
