"""
data_sources.py — Konektor data untuk screener HH/HL
Mendukung: yfinance (saham IDX/US) dan OKX public API (crypto).

BUKAN FINANCIAL ADVICE.
"""

from typing import Dict, List, Optional
import time
import requests

try:
    import streamlit as st
    _cache = st.cache_data
except Exception:  # supaya modul bisa diuji tanpa streamlit
    def _cache(**kwargs):
        def deco(fn):
            return fn
        return deco


OKX_BASE = "https://www.okx.com"

# Pemetaan interval → parameter tiap sumber
YF_INTERVAL = {"1D": "1d", "4H": "1h", "1W": "1wk"}   # yfinance tidak punya 4H native
OKX_BAR = {"1D": "1D", "4H": "4H", "1W": "1W"}


# ─────────────────────────────────────────────────────────────
# YFINANCE
# ─────────────────────────────────────────────────────────────

@_cache(ttl=3600, show_spinner=False)
def fetch_yfinance(ticker: str, interval: str = "1D", limit: int = 300) -> Optional[Dict]:
    """
    Ambil OHLCV dari Yahoo Finance.
    Saham IDX perlu sufiks .JK — contoh: BBCA.JK, TLKM.JK
    """
    try:
        import yfinance as yf
    except Exception as e:
        return {"error": f"library yfinance tidak tersedia: {e}"}

    yf_int = YF_INTERVAL.get(interval, "1d")
    # tentukan period yang cukup untuk `limit` bar
    if yf_int == "1d":
        period = "2y" if limit <= 400 else "5y"
    elif yf_int == "1wk":
        period = "5y" if limit <= 250 else "10y"
    else:
        period = "180d"  # batas Yahoo untuk data intraday 1h

    try:
        df = yf.Ticker(ticker).history(period=period, interval=yf_int, auto_adjust=False)
    except Exception as e:
        return {"error": f"yfinance gagal: {e}"}

    if df is None or df.empty:
        return {"error": "Tidak ada data (cek simbol — saham IDX butuh sufiks .JK)"}

    df = df.dropna(subset=["Close"]).tail(limit)
    if len(df) < 20:
        return {"error": f"Data terlalu sedikit ({len(df)} bar)"}

    # bar intraday butuh jam, kalau tidak beberapa bar menumpuk di tanggal yang sama
    fmt = "%Y-%m-%d %H:%M" if yf_int.endswith(("h", "m")) else "%Y-%m-%d"

    return {
        "close": df["Close"].astype(float).tolist(),
        "high": df["High"].astype(float).tolist(),
        "low": df["Low"].astype(float).tolist(),
        "volume": df["Volume"].astype(float).tolist(),
        "dates": [d.strftime(fmt) for d in df.index],
        "source": "yfinance",
    }


# ─────────────────────────────────────────────────────────────
# OKX
# ─────────────────────────────────────────────────────────────

@_cache(ttl=900, show_spinner=False)
def fetch_okx(inst_id: str, interval: str = "1D", limit: int = 300) -> Optional[Dict]:
    """
    Ambil OHLCV dari OKX public API (tanpa API key).
    Format instrumen:
      Spot     : BTC-USDT
      Perpetual: BTC-USDT-SWAP
    """
    bar = OKX_BAR.get(interval, "1D")
    url = f"{OKX_BASE}/api/v5/market/history-candles"
    rows: List[List[str]] = []
    after: Optional[str] = None

    try:
        # OKX maksimum 100 baris per panggilan → paginasi
        for _ in range(max(1, (limit // 100) + 1)):
            params = {"instId": inst_id, "bar": bar, "limit": "100"}
            if after:
                params["after"] = after
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            js = r.json()
            if js.get("code") != "0":
                return {"error": f"OKX error {js.get('code')}: {js.get('msg')}"}
            batch = js.get("data", [])
            if not batch:
                break
            rows.extend(batch)
            after = batch[-1][0]          # timestamp tertua di batch ini
            if len(rows) >= limit:
                break
            time.sleep(0.12)              # sopan terhadap rate limit
    except Exception as e:
        return {"error": f"OKX gagal: {e}"}

    if not rows:
        return {"error": "Tidak ada data (cek instId, mis. BTC-USDT-SWAP)"}

    rows = rows[:limit]
    rows.reverse()                        # OKX kirim terbaru dulu → balik jadi kronologis

    # bar intraday (4H, 1H, …) butuh jam supaya tidak menumpuk di tanggal yang sama
    intraday = bar.upper().endswith(("H", "M")) and not bar.upper().endswith("MON")

    try:
        out = {
            "close": [float(x[4]) for x in rows],
            "high": [float(x[2]) for x in rows],
            "low": [float(x[3]) for x in rows],
            "volume": [float(x[5]) for x in rows],
            "dates": [_ms_to_date(x[0], intraday) for x in rows],
            "source": "okx",
        }
    except (ValueError, IndexError) as e:
        return {"error": f"Format data OKX tak terduga: {e}"}

    if len(out["close"]) < 20:
        return {"error": f"Data terlalu sedikit ({len(out['close'])} bar)"}
    return out


def _ms_to_date(ms: str, intraday: bool = False) -> str:
    from datetime import datetime, timezone
    fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime(fmt)


# ─────────────────────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────────────────────

def fetch(ticker: str, source: str, interval: str = "1D", limit: int = 300) -> Dict:
    src = (source or "").strip().lower()
    if src in ("okx", "crypto"):
        return fetch_okx(ticker, interval, limit)
    return fetch_yfinance(ticker, interval, limit)


def okx_available_swaps(quote: str = "USDT") -> List[str]:
    """Daftar perpetual OKX — untuk membantu mengisi file xlsx."""
    try:
        r = requests.get(f"{OKX_BASE}/api/v5/public/instruments",
                         params={"instType": "SWAP"}, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", [])
        return sorted(d["instId"] for d in data
                      if d.get("settleCcy") == quote and d.get("state") == "live")
    except Exception:
        return []
