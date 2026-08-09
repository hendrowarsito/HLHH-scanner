"""
app.py — Screener Higher High / Higher Low
Streamlit Cloud ready. Sumber data: yfinance (saham) + OKX (crypto).

BUKAN FINANCIAL ADVICE. Alat screening, bukan penghasil sinyal entry.
"""

import io
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

from hhhl_detector import analyze_structure
from data_sources import fetch, okx_available_swaps

WIB = timezone(timedelta(hours=7))

st.set_page_config(page_title="Screener HH/HL", page_icon="📈", layout="wide")

GRADE_ORDER = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4, "-": 5}
GRADE_COLOR = {"A+": "#0b8043", "A": "#34a853", "B": "#f9ab00",
               "C": "#e8710a", "D": "#c5221f", "-": "#80868b"}

DEFAULT_TICKERS = pd.DataFrame({
    "Ticker": ["BBCA.JK", "TLKM.JK", "BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    "Source": ["yfinance", "yfinance", "okx", "okx"],
    "Nama": ["Bank Central Asia", "Telkom Indonesia", "Bitcoin Perp", "Ethereum Perp"],
    "Aktif": [True, True, True, True],
})


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

st.title("📈 Screener Higher High / Higher Low")
st.caption(
    "Menyaring instrumen dengan struktur uptrend (minimal N Higher High + N Higher Low). "
    "**Bukan financial advice** — ini alat screening, bukan sinyal entry."
)


# ─────────────────────────────────────────────────────────────
# SIDEBAR — DAFTAR TICKER
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📄 Daftar Instrumen")

    up = st.file_uploader(
        "Upload file .xlsx",
        type=["xlsx"],
        help="Kolom wajib: Ticker, Source. Opsional: Nama, Aktif",
    )

    if up is not None:
        try:
            tickers_df = pd.read_excel(up)
            st.success(f"{len(tickers_df)} baris dimuat")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")
            tickers_df = DEFAULT_TICKERS.copy()
    else:
        try:
            tickers_df = pd.read_excel("tickers.xlsx")
            st.info(f"Memakai tickers.xlsx bawaan ({len(tickers_df)} baris)")
        except Exception:
            tickers_df = DEFAULT_TICKERS.copy()
            st.warning("tickers.xlsx tidak ditemukan — memakai contoh bawaan")

    # normalisasi kolom
    tickers_df.columns = [str(c).strip().title() for c in tickers_df.columns]
    if "Ticker" not in tickers_df.columns:
        st.error("File harus punya kolom **Ticker**")
        st.stop()
    if "Source" not in tickers_df.columns:
        tickers_df["Source"] = "yfinance"
    if "Nama" not in tickers_df.columns:
        tickers_df["Nama"] = ""
    if "Aktif" not in tickers_df.columns:
        tickers_df["Aktif"] = True

    tickers_df = tickers_df[tickers_df["Aktif"].fillna(True).astype(bool)]
    tickers_df = tickers_df.dropna(subset=["Ticker"])
    st.metric("Instrumen aktif", len(tickers_df))

    # unduh template
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        DEFAULT_TICKERS.to_excel(w, index=False, sheet_name="Tickers")
    st.download_button("⬇️ Unduh template xlsx", buf.getvalue(),
                       "tickers_template.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.header("⚙️ Parameter")

    interval = st.selectbox("Timeframe", ["1D", "1W", "4H"], index=0,
                            help="4H hanya untuk OKX. yfinance memakai 1H sebagai pengganti.")
    lookback = st.slider("Lookback (bar)", 30, 300, 90, 10)

    col_a, col_b = st.columns(2)
    min_hh = col_a.number_input("Min HH", 1, 6, 2)
    min_hl = col_b.number_input("Min HL", 1, 6, 2)

    k_atr = st.slider("Sensitivitas (k × ATR)", 0.5, 3.0, 1.5, 0.1,
                      help="Kecil = lebih banyak swing terdeteksi. "
                           "Besar = hanya swing besar.")
    tolerance = st.slider("Toleransi HL (%)", 0.0, 2.0, 0.0, 0.1,
                          help="Kelonggaran agar noise wick tidak dianggap "
                               "pelanggaran struktur. 0 = paling ketat.")

    st.divider()
    st.subheader("Aturan struktur")
    include_tentative = st.checkbox(
        "Hitung swing tentatif", value=False,
        help="⚠️ Swing terakhir belum dikonfirmasi reversal. "
             "Aktifkan HANYA untuk watchlist, JANGAN untuk backtest "
             "(menimbulkan look-ahead bias).")
    break_on_lh = st.checkbox(
        "Lower High juga membatalkan struktur", value=False,
        help="Default: hanya pelanggaran HL yang membatalkan (Dow Theory). "
             "Lower High = peringatan.")
    exclude_broken = st.checkbox(
        "Hanya struktur yang belum pernah patah", value=False,
        help="Buang instrumen yang punya riwayat pelanggaran HL, "
             "meski segmen aktifnya sudah sah kembali.")

    st.divider()
    run = st.button("🔍 Jalankan Scan", type="primary", use_container_width=True)

    with st.expander("🔎 Cari kode OKX"):
        if st.button("Muat daftar perp USDT"):
            swaps = okx_available_swaps()
            if swaps:
                st.write(f"{len(swaps)} instrumen")
                st.dataframe(pd.DataFrame({"instId": swaps}),
                             height=240, use_container_width=True)
            else:
                st.warning("Gagal memuat — cek koneksi")


# ─────────────────────────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────────────────────────

if run:
    rows, errors, series_store = [], [], {}
    prog = st.progress(0.0, text="Memulai scan…")
    total = len(tickers_df)

    for i, (_, row) in enumerate(tickers_df.iterrows(), start=1):
        tk = str(row["Ticker"]).strip()
        src = str(row["Source"]).strip()
        nama = str(row.get("Nama", "") or "")
        prog.progress(i / total, text=f"[{i}/{total}] {tk}")

        try:
            data = fetch(tk, src, interval=interval, limit=max(lookback, 120))
        except Exception as e:
            errors.append({"Ticker": tk, "Pesan": f"fetch gagal: {e}"})
            continue
        if not data or "error" in data:
            errors.append({"Ticker": tk, "Pesan": (data or {}).get("error", "tidak diketahui")})
            continue

        closes = data["close"][-lookback:]
        highs = data["high"][-lookback:]
        lows = data["low"][-lookback:]

        try:
            r = analyze_structure(
                closes, ticker=tk, highs=highs, lows=lows,
                min_hh=int(min_hh), min_hl=int(min_hl), k_atr=k_atr,
                include_tentative=include_tentative,
                tolerance_pct=tolerance, break_on_lower_high=break_on_lh,
            )
        except Exception as e:
            errors.append({"Ticker": tk, "Pesan": f"analisa gagal: {e}"})
            continue

        if exclude_broken and r.break_count > 0:
            continue

        last = closes[-1]
        inval = r.invalidation_level
        rows.append({
            "Ticker": tk,
            "Nama": nama,
            "Source": data["source"],
            "Harga": round(last, 6),
            "Grade": r.grade,
            "Skor": r.score,
            "HH": r.hh_count,
            "HL": r.hl_count,
            "LH warn": r.lower_high_warnings,
            "Patah": r.break_count,
            "Lolos": r.passes,
            "Struktur utuh": r.structure_intact,
            "Invalidasi (HL)": round(inval, 6) if inval else None,
            "Jarak ke inval %": round((last - inval) / last * 100, 2) if inval and last else None,
            "Threshold %": r.threshold_pct,
            "Tren %/swing": round(r.trend_strength, 1),
            "Konsistensi": round(r.consistency, 2),
            "Swing tentatif": r.last_swing_tentative,
            "Catatan": " · ".join(r.notes),
        })
        series_store[tk] = {"data": data, "result": r}

    prog.empty()

    st.session_state["rows"] = rows
    st.session_state["errors"] = errors
    st.session_state["store"] = series_store
    st.session_state["scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
    st.session_state["params"] = dict(
        interval=interval, lookback=lookback, min_hh=int(min_hh), min_hl=int(min_hl),
        k_atr=k_atr, tolerance=tolerance, include_tentative=include_tentative,
        break_on_lh=break_on_lh, exclude_broken=exclude_broken)


# ─────────────────────────────────────────────────────────────
# HASIL
# ─────────────────────────────────────────────────────────────

rows = st.session_state.get("rows")

if rows is None:
    st.info("👈 Atur parameter di sidebar, lalu klik **Jalankan Scan**.")
    with st.expander("📖 Format file xlsx"):
        st.markdown("""
| Kolom | Wajib | Isi |
|---|---|---|
| **Ticker** | ✅ | Saham IDX pakai sufiks `.JK` (contoh `BBCA.JK`). Crypto OKX pakai `BTC-USDT-SWAP` |
| **Source** | ✅ | `yfinance` atau `okx` |
| Nama | — | Label bebas |
| Aktif | — | `TRUE` / `FALSE` untuk menyalakan/mematikan baris |
        """)
    st.stop()

df = pd.DataFrame(rows)
errors = st.session_state.get("errors", [])
store = st.session_state.get("store", {})

if df.empty:
    st.warning("Tidak ada instrumen yang berhasil dianalisa.")
else:
    passed = df[df["Lolos"] & df["Struktur utuh"]].copy()
    passed["_g"] = passed["Grade"].map(GRADE_ORDER)
    passed = passed.sort_values(["_g", "Skor"], ascending=[True, False]).drop(columns="_g")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dianalisa", len(df))
    c2.metric("Lolos", len(passed))
    c3.metric("Grade A/A+", int((passed["Grade"].isin(["A", "A+"])).sum()) if len(passed) else 0)
    c4.metric("Gagal ambil data", len(errors))
    st.caption(f"Scan: {st.session_state.get('scan_time','-')} · "
               f"params: {st.session_state.get('params',{})}")

    tab1, tab2, tab3, tab4 = st.tabs(["✅ Lolos", "📋 Semua", "📊 Detail", "⚠️ Error"])

    with tab1:
        if passed.empty:
            st.info("Tidak ada yang memenuhi syarat. Coba turunkan k×ATR atau perpanjang lookback.")
        else:
            show = passed[["Ticker", "Nama", "Grade", "Skor", "HH", "HL", "LH warn",
                           "Patah", "Harga", "Invalidasi (HL)", "Jarak ke inval %",
                           "Tren %/swing", "Threshold %", "Swing tentatif"]]
            st.dataframe(
                show.style.apply(
                    lambda s: [f"color:{GRADE_COLOR.get(v,'#000')};font-weight:700"
                               for v in s] if s.name == "Grade" else ["" for _ in s]),
                use_container_width=True, hide_index=True, height=460)

            st.download_button(
                "⬇️ Unduh hasil (CSV)",
                passed.to_csv(index=False).encode(),
                f"scan_hhhl_{datetime.now(WIB).strftime('%Y%m%d_%H%M')}.csv",
                "text/csv")
            st.caption("💡 Simpan CSV setiap scan. Tanpa log bertanggal, kamu tidak akan "
                       "bisa menguji apakah screener ini benar-benar menambah edge.")

    with tab2:
        st.dataframe(df, use_container_width=True, hide_index=True, height=460)

    with tab3:
        opts = list(store.keys())
        if not opts:
            st.info("Belum ada data.")
        else:
            sel = st.selectbox("Pilih instrumen", opts)
            entry = store[sel]
            d, r = entry["data"], entry["result"]
            lb = st.session_state["params"]["lookback"]
            closes = d["close"][-lb:]
            highs = d["high"][-lb:]
            lows = d["low"][-lb:]
            dates = d["dates"][-lb:]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Grade", r.grade, f"skor {r.score}")
            m2.metric("HH / HL", f"{r.hh_count} / {r.hl_count}")
            m3.metric("Invalidasi", r.invalidation_level or "—")
            m4.metric("Threshold", f"{r.threshold_pct}%")

            try:
                import plotly.graph_objects as go
                fig = go.Figure()

                # 1. bayangan rentang high–low sebagai konteks volatilitas
                fig.add_trace(go.Scatter(
                    x=dates, y=highs, mode="lines", name="Rentang H–L",
                    line=dict(width=0), hoverinfo="skip",
                    legendgroup="band", showlegend=False))
                fig.add_trace(go.Scatter(
                    x=dates, y=lows, mode="lines", name="Rentang H–L",
                    line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(26,115,232,0.10)", hoverinfo="skip",
                    legendgroup="band"))

                # 2. garis harga penutupan
                fig.add_trace(go.Scatter(
                    x=dates, y=closes, mode="lines", name="Close",
                    line=dict(color="#8a8f98", width=1.4, shape="spline",
                              smoothing=0.4),
                    hovertemplate="%{x}<br>Close %{y:.6g}<extra></extra>"))

                # 3. segmen struktur aktif + penanda swing
                seg = [s for s in r.active_segment if s.idx < len(dates)]
                if seg:
                    fig.add_trace(go.Scatter(
                        x=[dates[s.idx] for s in seg],
                        y=[s.price for s in seg],
                        mode="lines", name="Segmen aktif",
                        line=dict(color="#1a73e8", width=2.6),
                        hoverinfo="skip"))

                    for kind, label, color, symbol, pos in (
                        ("H", "Swing High", "#0b8043", "triangle-up", "top center"),
                        ("L", "Swing Low", "#c5221f", "triangle-down", "bottom center"),
                    ):
                        pts = [s for s in seg if s.kind == kind]
                        if not pts:
                            continue
                        fig.add_trace(go.Scatter(
                            x=[dates[s.idx] for s in pts],
                            y=[s.price for s in pts],
                            mode="markers+text", name=label,
                            text=[f"{s.kind}{'' if s.confirmed else '*'}" for s in pts],
                            textposition=pos,
                            textfont=dict(size=11, color=color),
                            marker=dict(color=color, size=9, symbol=symbol,
                                        line=dict(color="rgba(255,255,255,0.85)", width=1)),
                            hovertemplate=f"{label}<br>%{{x}}<br>%{{y:.6g}}<extra></extra>"))

                # 4. level invalidasi + zona di bawahnya
                inval = r.invalidation_level
                if inval:
                    floor = min(min(lows), inval)
                    pad = (max(highs) - floor) * 0.04 or inval * 0.01
                    fig.add_hrect(y0=floor - pad, y1=inval,
                                  fillcolor="rgba(197,34,31,0.06)",
                                  line_width=0, layer="below")
                    fig.add_hline(y=inval, line_dash="dot", line_width=1.6,
                                  line_color="#c5221f")
                    fig.add_annotation(
                        xref="paper", x=0.005, y=inval, yanchor="bottom",
                        text=f"Invalidasi {inval:g}", showarrow=False,
                        font=dict(size=11, color="#c5221f"),
                        bgcolor="rgba(255,255,255,0.75)", borderpad=2)

                fig.update_layout(
                    height=460,
                    margin=dict(l=0, r=8, t=52, b=78),
                    title=dict(
                        text=f"<b>{sel}</b>  ·  {st.session_state['params']['interval']}"
                             f"  ·  grade {r.grade}",
                        x=0, xanchor="left", font=dict(size=15)),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    legend=dict(
                        orientation="h", yanchor="top", y=-0.16,
                        xanchor="left", x=0,
                        bgcolor="rgba(0,0,0,0)", borderwidth=0,
                        font=dict(size=11), itemsizing="constant"),
                )
                fig.update_xaxes(showgrid=False, showline=True,
                                 linecolor="rgba(128,134,139,0.35)",
                                 ticks="outside", tickcolor="rgba(128,134,139,0.35)",
                                 nticks=6)
                fig.update_yaxes(showgrid=True, gridcolor="rgba(128,134,139,0.18)",
                                 zeroline=False, side="right", nticks=6)

                st.plotly_chart(
                    fig, use_container_width=True,
                    config={"displayModeBar": False, "responsive": True,
                            "scrollZoom": False})
            except Exception as e:
                st.warning(f"Chart tidak tersedia: {e}")
                st.line_chart(pd.DataFrame({"Close": closes}, index=dates))

            st.write("**Seluruh swing:**", " → ".join(str(s) for s in r.swings))
            st.write("**Segmen aktif:**", " → ".join(str(s) for s in r.active_segment))
            if r.notes:
                for n in r.notes:
                    st.warning(n)

    with tab4:
        if errors:
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
            st.caption("Penyebab umum: simbol salah (saham IDX butuh `.JK`), "
                       "instrumen delisted, atau rate limit — coba lagi beberapa menit.")
        else:
            st.success("Tidak ada error.")

st.divider()
st.caption(
    "⚠️ **Bukan financial advice.** Screener ini menjawab *apa yang layak dilihat*, "
    "bukan *apa yang layak dibeli*. Trigger entry tetap dari checklist tervalidasi. "
    "Semua klaim performa belum divalidasi sampai protokol uji forward-return dijalankan."
)
