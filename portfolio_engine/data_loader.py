"""
data_loader.py - Descarga y almacenamiento en caché de universo diversificado de acciones
con calendario completo de dividendos e historial OHLCV usando la API directa de Yahoo Finance.
"""

import os
import time
import json
import pickle
import urllib.request
import pandas as pd
import numpy as np

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 25 Acciones de alta liquidez y dividendos sólidos en múltiples sectores (Tech, Salud, Financiero, Energía, Consumo, Industria)
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",  # Tech
    "JNJ", "PFE", "ABBV", "UNH",              # Salud
    "JPM", "BAC", "V", "MA",                  # Financiero
    "XOM", "CVX",                             # Energía
    "PG", "KO", "PEP", "COST", "WMT", "MCD",  # Consumo estable/discrecional
        "CAT", "HON", "NEE", "LIN"                # Industria / Utilities / Materiales
]

# 40 Acciones de alta liquidez multi-sector (extensión del universo 25) para tests de
# robustez de cross-section (P5.1). Todas cotizan en NYSE/NASDAQ y tienen historial
# OHLCV+dividendos en Yahoo Finance.
DEFAULT_UNIVERSE_40 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AMD", "INTC", "NFLX", "TSLA",  # Tech
    "JNJ", "PFE", "ABBV", "UNH", "MRK",                                              # Salud
    "JPM", "BAC", "V", "MA", "GS", "MS",                                             # Financiero
    "XOM", "CVX", "COP", "SLB",                                                      # Energía
    "PG", "KO", "PEP", "COST", "WMT", "MCD",                                         # Consumo
    "CAT", "HON", "LIN", "NEE", "EXC",                                               # Industria / Utilities
    "O", "PLD", "WELL",                                                              # Real Estate
    "DIS",                                                                          # Comunicaciones
]

def fetch_ticker_data(symbol, range_str="5y"):
    """
    Descarga OHLCV y dividendos exactos con reintentos y cabeceras estándar.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}&events=div%7Csplit"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote = result["indicators"]["quote"][0]
                
                df = pd.DataFrame({
                    "open": quote["open"],
                    "high": quote["high"],
                    "low": quote["low"],
                    "close": quote["close"],
                    "volume": quote["volume"]
                }, index=pd.to_datetime(timestamps, unit="s", utc=True))
                
                # Manejar splits si los hay o forward fill
                df = df.ffill().bfill()
                
                # Dividendos
                df["dividend"] = 0.0
                events = result.get("events", {})
                if "dividends" in events:
                    for k, v in events["dividends"].items():
                        dt = pd.to_datetime(v["date"], unit="s", utc=True)
                        amt = float(v["amount"])
                        # Encontrar índice exacto o el más cercano anterior/posterior
                        pos = df.index.searchsorted(dt)
                        if pos < len(df):
                            df.iloc[pos, df.columns.get_loc("dividend")] += amt
                
                return df
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
    return None

def load_or_fetch_universe(symbols=None, range_str="5y", force_refresh=False):
    """
    Descarga o carga de caché el panel completo de acciones con dividendos.
    Retorna un DataFrame MultiIndex (symbol, date) y una serie de fechas.
    """
    if symbols is None:
        symbols = DEFAULT_UNIVERSE
        
    cache_file = os.path.join(CACHE_DIR, f"universe_{len(symbols)}_{range_str}.pkl")
    if os.path.exists(cache_file) and not force_refresh:
        with open(cache_file, "rb") as f:
            data = pickle.load(f)
            print(f"[DataLoader] Universo cargado de caché: {len(data['symbols'])} tickers, rango {data['start']} a {data['end']}")
            return data
            
    print(f"[DataLoader] Descargando universo de {len(symbols)} activos con dividendos...")
    all_dfs = {}
    for sym in symbols:
        df = fetch_ticker_data(sym, range_str=range_str)
        if df is not None and len(df) > 100:
            all_dfs[sym] = df
            print(f"  -> {sym}: {len(df)} barras, {int((df['dividend'] > 0).sum())} eventos de dividendos")
        else:
            print(f"  [ALERTA] No se pudo obtener datos válidos para {sym}")
        time.sleep(0.3)
        
    # Unificar en un panel común
    panel_dict = {}
    for sym, df in all_dfs.items():
        df_clean = df[["open", "high", "low", "close", "volume", "dividend"]].copy()
        df_clean["symbol"] = sym
        panel_dict[sym] = df_clean
        
    panel = pd.concat(panel_dict.values())
    panel = panel.reset_index().rename(columns={"index": "date"})
    panel = panel.set_index(["symbol", "date"]).sort_index()
    
    dates = sorted(panel.index.get_level_values("date").unique())
    
    data_pkg = {
        "panel": panel,
        "symbols": list(all_dfs.keys()),
        "dates": dates,
        "start": str(dates[0].date()),
        "end": str(dates[-1].date())
    }
    
    with open(cache_file, "wb") as f:
        pickle.dump(data_pkg, f)
        
    print(f"[DataLoader] Guardado en caché exitosamente: {cache_file}")
    return data_pkg

if __name__ == "__main__":
    pkg = load_or_fetch_universe(range_str="5y")
    print(f"Universo listo: {len(pkg['symbols'])} activos desde {pkg['start']} hasta {pkg['end']}")
