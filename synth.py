"""Datos sintéticos (vol persistente, dirección impredecible) con el MISMO formato que KuCoin.
Sirve para verificar el pipeline offline:  python synth.py && python loop.py baseline"""
import os, numpy as np, pandas as pd
from prepare import DATA_DIR, RAW_PATH
rng = np.random.default_rng(7)
N, S, sub = 24 * 730, 50, 4
t0 = int(pd.Timestamp("2024-09-01").timestamp())
common = np.zeros(N); x = 0.0
for i in range(N):
    x = 0.997 * x + 0.03 * rng.standard_normal(); common[i] = x
rows = []
for k in range(S):
    sym = "BTC-USDT" if k == 0 else f"C{k:02d}-USDT"
    xi = np.zeros(N); z = 0.0
    for i in range(N):
        z = 0.99 * z + 0.06 * rng.standard_normal(); xi[i] = z
    hours = np.arange(N)
    sig = np.exp(np.log(0.006 + 0.002 * (k % 5)) + common + xi + 0.15 * np.sin(2 * np.pi * (hours % 24) / 24))
    mkt = rng.standard_normal(N)
    r = sig[:, None] * (0.5 * mkt[:, None] + 0.87 * rng.standard_normal((N, sub))) / np.sqrt(sub)
    path = 100 * np.exp(np.cumsum(r.reshape(-1))).reshape(N, sub)
    op = np.r_[100.0, path[:-1, -1]]
    cl, hi, lo = path[:, -1], path.max(1), path.min(1)
    hi, lo = np.maximum(hi, op), np.minimum(lo, op)
    vol = np.exp(8 + 4 * (np.log(sig) - np.log(0.008)) + 0.3 * rng.standard_normal(N))
    rows.append(pd.DataFrame(dict(time=t0 + 3600 * hours, open=op, close=cl, high=hi, low=lo, volume=vol,
                                  turnover=vol * cl, sym=sym)))
os.makedirs(DATA_DIR, exist_ok=True)
pd.concat(rows, ignore_index=True).to_pickle(RAW_PATH)
print("sintético guardado en", RAW_PATH)
