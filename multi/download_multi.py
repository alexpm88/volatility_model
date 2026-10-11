"""download_multi.py — Datos REALES diarios (Yahoo Finance) para el sistema multi-activo.
Activos: acciones (SPY, QQQ, GDX), oro y metales (GLD, SLV, GC=F, SI=F), crypto (BTC-USD).
Fuente: ajustado por dividendos/splits (auto_adjust=True). Guarda multi/multi_raw.pkl con el
mismo formato crudo que prepare.py (time, open, close, high, low, volume, turnover, sym).

Uso:  python multi/download_multi.py   (reintenta por ticker, 429-safe con backoff)
"""
import os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TICKERS = {  # sym -> clase de activo
    "SPY": "equity", "QQQ": "equity", "GDX": "equity_gold_miners",
    "GLD": "gold", "GC=F": "gold_futures", "SLV": "silver", "SI=F": "silver_futures",
    "BTC-USD": "crypto",
}
COST_BPS = {"equity": 5, "equity_gold_miners": 5, "gold": 5, "silver": 5, "crypto": 10,
            "gold_futures": 2, "silver_futures": 2}   # ida+vuelta razonable por lado (comisión+spread+slippage)


def fetch_one(tk, tries=4):
    import yfinance as yf
    for i in range(tries):
        try:
            d = yf.download(tk, period="max", interval="1d", auto_adjust=True, progress=False, threads=False)
            if isinstance(d.columns, pd.MultiIndex):      # yf>=0.2.5 devuelve columnas multi-ticker
                d.columns = d.columns.get_level_values(0)
            d.columns = [str(c).lower() for c in d.columns]   # Open->open, Close->close, ...
            d = d.dropna(subset=["close"])
            if len(d) > 300:
                return d
        except Exception:
            pass
        time.sleep(8 * (i + 1))                            # backoff para el rate-limit de Yahoo (429)
    raise RuntimeError(f"Yahoo no dio datos para {tk}")


def main():
    rows, meta = [], []
    for tk, cls in TICKERS.items():
        d = fetch_one(tk)
        d = d.reset_index().rename(columns={"Date": "ts"})
        d["ts"] = pd.to_datetime(d["ts"]).dt.tz_localize(None).dt.floor("D")
        d = d.drop_duplicates("ts").sort_values("ts")
        d["sym"] = tk
        d["turnover"] = d["volume"] * d["close"]
        d["asset_class"] = cls
        rows.append(d[["ts", "open", "close", "high", "low", "volume", "turnover", "sym", "asset_class"]])
        meta.append(dict(sym=tk, asset_class=cls, cost_bps=COST_BPS[cls],
                         start=str(d["ts"].iloc[0].date()), end=str(d["ts"].iloc[-1].date()), n=len(d)))
        print(f"{tk:8s} {cls:18s} {d['ts'].iloc[0].date()} -> {d['ts'].iloc[-1].date()}  {len(d)} dias", flush=True)
    raw = pd.concat(rows, ignore_index=True)
    raw["time"] = (raw["ts"].astype("int64") // 10 ** 9).astype("int64")   # formato igual que KuCoin (unix seg)
    raw.to_pickle(os.path.join(HERE, "multi_raw.pkl"))
    pd.DataFrame(meta).to_csv(os.path.join(HERE, "multi_universe.csv"), index=False)
    print("guardado:", os.path.join(HERE, "multi_raw.pkl"), raw.shape)


if __name__ == "__main__":
    main()
