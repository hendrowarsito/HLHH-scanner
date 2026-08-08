"""
hhhl_detector.py — Detektor Higher High / Higher Low untuk screening saham & crypto
Versi 1.0 | Untuk integrasi ke Cryptoscreener5

BUKAN FINANCIAL ADVICE. Alat screening, bukan sinyal entry.

Prinsip desain:
1. Swing point ditentukan lewat ZigZag dengan threshold ADAPTIF (berbasis ATR),
   bukan persentase tetap — karena volatilitas tiap saham berbeda.
2. Swing terakhir SELALU tentatif sampai ada reversal >= threshold.
   Perhitungan default hanya memakai swing TERKONFIRMASI (anti look-ahead bias).
3. Output menyertakan skor kualitas, bukan cuma lolos/tidak lolos.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal, Sequence
import math


# ─────────────────────────────────────────────────────────────
# STRUKTUR DATA
# ─────────────────────────────────────────────────────────────

@dataclass
class Swing:
    idx: int
    price: float
    kind: Literal["H", "L"]
    confirmed: bool = True

    def __repr__(self):
        return f"{self.kind}{self.price:g}{'' if self.confirmed else '*'}@{self.idx}"


@dataclass
class StructureResult:
    ticker: str = ""
    swings: List[Swing] = field(default_factory=list)          # seluruh swing
    active_segment: List[Swing] = field(default_factory=list)   # segmen struktur AKTIF
    hh_count: int = 0                                           # dihitung dari segmen aktif
    hl_count: int = 0
    passes: bool = False
    threshold_pct: float = 0.0

    # struktur & pelanggaran
    n_segments: int = 1              # >1 berarti pernah patah lalu terbentuk ulang
    break_count: int = 0             # jumlah pelanggaran HL sepanjang data
    last_break_idx: Optional[int] = None
    lower_high_warnings: int = 0     # LH: peringatan, bukan pembatal (Dow)

    # metrik kualitas
    grade: str = "-"
    score: float = 0.0
    trend_strength: float = 0.0      # kemiringan struktur, % per swing
    consistency: float = 0.0         # 0-1, seberapa konsisten HH/HL tanpa pelanggaran
    last_swing_tentative: bool = True
    bars_since_last_swing: int = 0
    structure_intact: bool = True    # harga belum menembus HL terakhir
    invalidation_level: Optional[float] = None
    notes: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# 1. THRESHOLD ADAPTIF
# ─────────────────────────────────────────────────────────────

def atr_pct(highs: Sequence[float], lows: Sequence[float],
            closes: Sequence[float], period: int = 14) -> float:
    """ATR sebagai % dari harga terakhir. Dipakai untuk menormalkan threshold."""
    n = len(closes)
    if n < 2:
        return 2.0
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    window = trs[-period:] if len(trs) >= period else trs
    atr = sum(window) / len(window)
    return (atr / closes[-1]) * 100.0 if closes[-1] else 2.0


def adaptive_threshold(atr_percent: float, k: float = 1.5,
                       floor: float = 2.0, cap: float = 15.0) -> float:
    """
    Threshold ZigZag = k x ATR%.
    k=1.5 berarti: pergerakan balik dianggap swing kalau melebihi 1.5x volatilitas harian normal.
    Dibatasi floor/cap supaya tidak absurd di saham sangat tenang atau sangat liar.
    """
    return max(floor, min(cap, k * atr_percent))


# ─────────────────────────────────────────────────────────────
# 2. DETEKSI SWING (ZIGZAG)
# ─────────────────────────────────────────────────────────────

def detect_swings(prices: Sequence[float], threshold_pct: float) -> List[Swing]:
    """
    ZigZag. Swing TERAKHIR selalu ditandai confirmed=False karena belum ada
    reversal sebesar threshold yang mengonfirmasinya.
    """
    if len(prices) < 3 or threshold_pct <= 0:
        return []

    t = threshold_pct / 100.0
    swings: List[Swing] = []
    direction: Optional[str] = None

    # Fase inisialisasi: lacak min DAN max berjalan sampai salah satunya
    # ditinggalkan sejauh threshold. Yang lebih dulu terpicu menentukan arah.
    min_idx, min_price = 0, prices[0]
    max_idx, max_price = 0, prices[0]
    piv_idx, piv_price = 0, prices[0]

    for i in range(1, len(prices)):
        p = prices[i]

        if direction is None:
            if p < min_price:
                min_idx, min_price = i, p
            if p > max_price:
                max_idx, max_price = i, p

            up_move = (p - min_price) / min_price if min_price else 0
            down_move = (max_price - p) / max_price if max_price else 0

            if up_move >= t and min_idx <= max_idx:
                direction = "up"
                swings.append(Swing(min_idx, min_price, "L"))
                piv_idx, piv_price = i, p
            elif down_move >= t and max_idx <= min_idx:
                direction = "down"
                swings.append(Swing(max_idx, max_price, "H"))
                piv_idx, piv_price = i, p
            elif up_move >= t:
                direction = "up"
                swings.append(Swing(min_idx, min_price, "L"))
                piv_idx, piv_price = i, p
            elif down_move >= t:
                direction = "down"
                swings.append(Swing(max_idx, max_price, "H"))
                piv_idx, piv_price = i, p
            continue

        if piv_price == 0:
            continue
        chg = (p - piv_price) / piv_price

        if direction == "up":
            if p >= piv_price:
                piv_idx, piv_price = i, p
            elif chg <= -t:
                swings.append(Swing(piv_idx, piv_price, "H"))
                direction = "down"
                piv_idx, piv_price = i, p
        else:
            if p <= piv_price:
                piv_idx, piv_price = i, p
            elif chg >= t:
                swings.append(Swing(piv_idx, piv_price, "L"))
                direction = "up"
                piv_idx, piv_price = i, p

    if direction is not None:
        swings.append(Swing(piv_idx, piv_price,
                            "H" if direction == "up" else "L", confirmed=False))
    return swings


# ─────────────────────────────────────────────────────────────
# 2b. SEGMENTASI STRUKTUR (ATURAN KETAT)
# ─────────────────────────────────────────────────────────────

def segment_structure(swings: List[Swing],
                      tolerance_pct: float = 0.0,
                      break_on_lower_high: bool = False) -> List[List[Swing]]:
    """
    ATURAN INTI: HL baru TIDAK BOLEH <= HL sebelumnya. Kalau dilanggar,
    struktur GAGAL dan segmen baru dimulai dari titik pelanggaran itu.

    Equal low dihitung sebagai PELANGGARAN (harus lebih tinggi, bukan sama).
    tolerance_pct > 0 memberi kelonggaran, mis. 0.3 = low boleh 0,3% lebih
    rendah tanpa dianggap patah (untuk meredam noise wick).

    Lower High secara default hanya PERINGATAN, bukan pembatal — sesuai
    Dow Theory: uptrend baru batal ketika HL ditembus, bukan saat HH gagal.
    Set break_on_lower_high=True untuk aturan yang lebih ketat lagi.
    """
    tol = tolerance_pct / 100.0
    segments: List[List[Swing]] = []
    cur: List[Swing] = []
    last_low: Optional[float] = None
    last_high: Optional[float] = None

    for s in swings:
        broken = False
        if s.kind == "L":
            if last_low is not None and s.price <= last_low * (1 - tol):
                broken = True
        else:
            if break_on_lower_high and last_high is not None \
               and s.price <= last_high * (1 - tol):
                broken = True

        if broken:
            if cur:
                segments.append(cur)
            cur = [s]
            last_low = s.price if s.kind == "L" else None
            last_high = s.price if s.kind == "H" else None
        else:
            cur.append(s)
            if s.kind == "L":
                last_low = s.price
            else:
                last_high = s.price

    if cur:
        segments.append(cur)
    return segments


# ─────────────────────────────────────────────────────────────
# 3. ANALISA STRUKTUR
# ─────────────────────────────────────────────────────────────

def analyze_structure(
    prices: Sequence[float],
    ticker: str = "",
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    min_hh: int = 2,
    min_hl: int = 2,
    k_atr: float = 1.5,
    fixed_threshold_pct: Optional[float] = None,
    include_tentative: bool = False,
    tolerance_pct: float = 0.0,
    break_on_lower_high: bool = False,
) -> StructureResult:
    """
    Analisa struktur HH/HL.

    include_tentative=False (DEFAULT, disarankan):
        Hanya swing terkonfirmasi yang dihitung. Ini yang benar untuk backtest
        dan untuk menghindari klaim struktur yang belum terbukti.
    include_tentative=True:
        Swing terakhir yang belum terkonfirmasi ikut dihitung. Berguna untuk
        watchlist "hampir memenuhi", TAPI jangan dipakai untuk backtest.
    """
    res = StructureResult(ticker=ticker)
    if len(prices) < 5:
        res.notes.append("Data terlalu pendek")
        return res

    if fixed_threshold_pct is not None:
        th = fixed_threshold_pct
    else:
        h = highs if highs is not None else prices
        l = lows if lows is not None else prices
        th = adaptive_threshold(atr_pct(h, l, prices), k=k_atr)
    res.threshold_pct = round(th, 2)

    swings = detect_swings(prices, th)
    res.swings = swings
    if len(swings) < 3:
        res.notes.append("Swing terdeteksi < 3 — struktur belum terbentuk")
        return res

    used = swings if include_tentative else [s for s in swings if s.confirmed]

    # ATURAN KETAT: pecah jadi segmen; HL yang dilanggar = struktur gagal
    segments = segment_structure(used, tolerance_pct=tolerance_pct,
                                 break_on_lower_high=break_on_lower_high)
    res.n_segments = len(segments)
    res.break_count = max(0, len(segments) - 1)
    if res.break_count > 0:
        res.last_break_idx = segments[-1][0].idx
        res.notes.append(
            f"Struktur pernah PATAH {res.break_count}x — dihitung hanya dari "
            f"segmen aktif (mulai bar {res.last_break_idx})")

    active = segments[-1] if segments else []
    res.active_segment = active

    hs = [s for s in active if s.kind == "H"]
    ls = [s for s in active if s.kind == "L"]

    hh = sum(1 for i in range(1, len(hs)) if hs[i].price > hs[i - 1].price)
    hl = sum(1 for i in range(1, len(ls)) if ls[i].price > ls[i - 1].price)
    lh = sum(1 for i in range(1, len(hs)) if hs[i].price <= hs[i - 1].price)

    res.hh_count, res.hl_count = hh, hl
    res.lower_high_warnings = lh
    res.passes = (hh >= min_hh and hl >= min_hl)

    # Di segmen aktif, HL selalu naik (by construction). Konsistensi hanya
    # menghukum Lower High yang muncul di dalam segmen.
    total_trans = hh + hl + lh
    res.consistency = (hh + hl) / total_trans if total_trans else 0.0
    if lh > 0:
        res.notes.append(f"{lh} Lower High di segmen aktif — momentum melemah "
                         f"(peringatan, bukan pembatal)")

    # kekuatan tren: rata-rata kenaikan % antar swing searah
    gains = []
    for seq in (hs, ls):
        for i in range(1, len(seq)):
            if seq[i - 1].price:
                gains.append((seq[i].price - seq[i - 1].price) / seq[i - 1].price * 100)
    res.trend_strength = sum(gains) / len(gains) if gains else 0.0

    res.last_swing_tentative = not swings[-1].confirmed
    res.bars_since_last_swing = len(prices) - 1 - swings[-1].idx

    # invalidasi = HL terakhir yang terkonfirmasi
    conf_lows = [s for s in active if s.kind == "L" and s.confirmed]
    if conf_lows:
        res.invalidation_level = conf_lows[-1].price
        res.structure_intact = prices[-1] > conf_lows[-1].price
        if not res.structure_intact:
            res.notes.append("Harga sudah di bawah HL terakhir — struktur PATAH")
    else:
        # segmen aktif belum punya HL terkonfirmasi = struktur belum berdiri
        res.structure_intact = False
        res.notes.append("Segmen aktif belum punya HL terkonfirmasi — "
                         "struktur belum berdiri kembali")

    # grading
    score = 0.0
    score += min(hh, 4) * 12
    score += min(hl, 4) * 12
    score += res.consistency * 25
    score += max(0.0, min(res.trend_strength, 20)) * 1.0
    if not res.structure_intact:
        score *= 0.4
    if res.break_count > 0:
        score *= max(0.6, 1.0 - 0.15 * res.break_count)
    if res.lower_high_warnings > 0:
        score *= max(0.7, 1.0 - 0.15 * res.lower_high_warnings)
    if res.last_swing_tentative and res.bars_since_last_swing < 2:
        score *= 0.9
        res.notes.append("Swing terakhir masih tentatif (belum ada reversal konfirmasi)")
    res.score = round(min(score, 100), 1)

    res.grade = ("A+" if res.score >= 85 else "A" if res.score >= 70
                 else "B" if res.score >= 55 else "C" if res.score >= 40 else "D")
    return res


# ─────────────────────────────────────────────────────────────
# 4. SCREENER
# ─────────────────────────────────────────────────────────────

def screen(universe: dict, lookback: int = 60, **kwargs) -> List[StructureResult]:
    """
    universe: {"TICKER": {"close": [...], "high": [...], "low": [...]}, ...}
    Mengembalikan hasil yang lolos, terurut dari skor tertinggi.
    """
    out = []
    for tk, d in universe.items():
        closes = list(d["close"])[-lookback:]
        hi = list(d.get("high", closes))[-lookback:]
        lo = list(d.get("low", closes))[-lookback:]
        try:
            r = analyze_structure(closes, ticker=tk, highs=hi, lows=lo, **kwargs)
            if r.passes:
                out.append(r)
        except Exception as e:  # noqa
            print(f"[skip] {tk}: {e}")
    return sorted(out, key=lambda r: r.score, reverse=True)


# ─────────────────────────────────────────────────────────────
# UJI DENGAN DATA CONTOH
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    data = [70,73,74,76,80,75,79,80,80,85,90,95,93,87,85,88,93,95,94,93,95,100]

    print("=" * 66)
    print("UJI 1 — Sensitivitas threshold (data contoh)")
    print("=" * 66)
    for th in [3, 5, 6, 7, 10, 12]:
        sw = detect_swings(data, th)
        print(f"  {th:>2}% -> {sw}")

    print()
    print("=" * 66)
    print("UJI 2 — Confirmed only vs termasuk tentatif")
    print("=" * 66)
    for inc in (False, True):
        r = analyze_structure(data, "CONTOH", fixed_threshold_pct=5, include_tentative=inc)
        label = "termasuk tentatif" if inc else "confirmed only  "
        print(f"  {label} | HH={r.hh_count} HL={r.hl_count} "
              f"lolos={r.passes} grade={r.grade} skor={r.score}")

    print()
    print("=" * 66)
    print("UJI 3 — Threshold adaptif (ATR-based)")
    print("=" * 66)
    r = analyze_structure(data, "CONTOH", include_tentative=True)
    print(f"  threshold otomatis : {r.threshold_pct}%")
    print(f"  swings             : {r.swings}")
    print(f"  HH={r.hh_count}  HL={r.hl_count}  lolos={r.passes}")
    print(f"  grade={r.grade}  skor={r.score}")
    print(f"  consistency        : {r.consistency:.0%}")
    print(f"  trend strength     : {r.trend_strength:.1f}% per swing")
    print(f"  invalidasi (HL)    : {r.invalidation_level}")
    print(f"  struktur utuh      : {r.structure_intact}")
    print(f"  catatan            : {r.notes}")

    print()
    print("=" * 66)
    print("UJI 4 — Kasus negatif (downtrend & sideways)")
    print("=" * 66)
    down = [100,95,97,88,90,82,85,78,80,72,75,68,70,63,65,60]
    side = [100,102,98,101,99,103,97,100,102,98,101,99,100,101,99,100]
    for nm, d in (("DOWNTREND", down), ("SIDEWAYS ", side)):
        r = analyze_structure(d, nm, include_tentative=True)
        print(f"  {nm} | th={r.threshold_pct}% HH={r.hh_count} HL={r.hl_count} "
              f"lolos={r.passes} grade={r.grade}")

    print()
    print("=" * 66)
    print("UJI 5 — Struktur patah (HH/HL lalu jatuh di bawah HL terakhir)")
    print("=" * 66)
    broken = data + [92, 84, 78, 72]
    r = analyze_structure(broken, "PATAH", include_tentative=True)
    print(f"  swings        : {r.swings}")
    print(f"  HH={r.hh_count} HL={r.hl_count} lolos={r.passes} grade={r.grade} skor={r.score}")
    print(f"  struktur utuh : {r.structure_intact}")
    print(f"  catatan       : {r.notes}")
