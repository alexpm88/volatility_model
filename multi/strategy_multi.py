"""strategy_multi.py — LO ÚNICO QUE EL LOOP MULTI MODIFICA.
Contrato (igual que strategy.py pero diario, multi-activo):
  build_features(panel) -> DataFrame con el MISMO índice (sym, ts). SOLO info <= t.
  fit(Xtr, ytr, task, h) -> objeto con .predict(X)   (task: dir | vol | exp)
Si build_features mira al futuro, prepare_multi.check_causal aborta.
Features diarias: retornos multi-escala, volatilidad realizada HAR-extendida, ciclos de vol,
momentum de signo, anatomía de vela, volumen, estacionalidad (día de semana/mes) y sección
cruzada (mercado, breadth, rankings, lead de BTC).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

PARAMS = {'max_iter': 350, 'lr': 0.02, 'max_depth': 3, 'min_leaf': 250, 'l2': 1.0, 'calib': 'none', 'shrink': 0.75}
SPACE = {"max_iter": [100, 200, 350], "lr": [0.02, 0.05, 0.08], "max_depth": [2, 3, 4],
         "min_leaf": [50, 100, 250], "l2": [0.0, 1.0, 5.0], "calib": ["platt", "none"],
         "shrink": [0.5, 0.75, 1.0]}


def _tr(s, fn):
    return s.groupby(level="sym").transform(fn)


def build_features(panel):
    c, o, hi, lo, v = (panel[k] for k in ("close", "open", "high", "low", "volume"))
    lc = np.log(c)
    g = lc.groupby(level="sym")
    lr = g.diff()
    F = pd.DataFrame(index=panel.index)
    for k in (1, 5, 10, 21, 63, 252):                      # retornos multi-horizonte
        F[f"ret_{k}"] = lc - g.shift(k)
    up = (lr > 0).astype(float).where(lr.notna())          # momentum de signo
    for k in (5, 21, 63):
        F[f"pup_{k}"] = _tr(up, lambda s, k=k: s.rolling(k).mean())
    F["body"] = (c - o) / o                                # anatomía de la vela diaria
    F["range"] = (hi - lo) / o
    F["close_pos"] = (c - lo) / (hi - lo + 1e-12)
    lv = np.log1p(v)                                       # volumen
    F["dvol_1"] = lv - lv.groupby(level="sym").shift(1)
    F["dvol_21"] = lv - lv.groupby(level="sym").shift(21)
    F["vol_z"] = (lv - _tr(lv, lambda s: s.rolling(63).mean())) / (_tr(lv, lambda s: s.rolling(63).std()) + 1e-9)
    rv = {}                                                # volatilidad realizada multi-escala
    for w in (5, 21, 63, 252):
        rv[w] = np.log(np.sqrt(_tr(lr ** 2, lambda s, w=w: s.rolling(w).mean())) + 1e-6)
        F[f"lrv_{w}"] = rv[w]
    park = (np.log(hi / lo) ** 2) / (4 * np.log(2))
    F["lpark_21"] = np.log(np.sqrt(_tr(park, lambda s: s.rolling(21).mean())) + 1e-6)
    F["cyc_5_21"], F["cyc_21_63"], F["cyc_63_252"] = rv[5] - rv[21], rv[21] - rv[63], rv[63] - rv[252]
    # V5.1-M1: vol-term-premium inversion 5d-vs-63d (log ratio corto/cuarto trimestre).
    # Papers term-premium inversion preceden regime shifts; no redundante con cyc_5_21/cyc_63_252 (escala quarter).
    # Causal: rv[w] es log-RV pasado (rolling); check_causal valida.
    F["vol_term_5_63"] = rv[5] - rv[63]   # <0: compresión vol corto vs cuarto-trim (régimen estable/bajo-vol)
    F["jump_21"] = F["lpark_21"] - rv[21]                  # salto: Parkinson vs cierre-cierre
    # ---- DESCOMPOSICIÓN DE SALTOS MULTI: Bipower variation + Signed jumps causal ----
    abs_lr = lr.abs()
    _bp = (np.pi / 2.0) * _tr(abs_lr * _tr(abs_lr, lambda s: s.shift(1)), lambda s: s.rolling(21).mean())
    _rv21_lin = _tr(lr ** 2, lambda s: s.rolling(21).mean())
    F["jump_ratio_21"] = ((_rv21_lin - _bp) / (_rv21_lin + 1e-9)).clip(lower=0.0)
    F["lbp_21"] = np.log(np.sqrt(_bp.clip(lower=0.0)) + 1e-6)
    up2, dn2 = lr.clip(lower=0) ** 2, (-lr).clip(lower=0) ** 2
    _pos_lin = _tr(up2, lambda s: s.rolling(21).mean())
    _neg_lin = _tr(dn2, lambda s: s.rolling(21).mean())
    F["signed_jump_21"] = (_pos_lin - _neg_lin) / (_rv21_lin + 1e-9)
    gap = o / c.groupby(level="sym").shift(1)              # salto nocturno (causal: usa open de t)
    F["gap"] = np.log(gap)
    F["gap_abs_21"] = _tr(np.abs(F["gap"]), lambda s: s.rolling(21).mean())
    F["vov_63"] = _tr(rv[21], lambda s: s.rolling(63).std())
    F["vmax_63"] = _tr(rv[21], lambda s: s.rolling(63).max()) - rv[21]     # distancia al máximo de vol
    F["vmin_63"] = rv[21] - _tr(rv[21], lambda s: s.rolling(63).min())     # distancia al mínimo de vol
    # ---- NATR (Normalized ATR) y True Range Normalizado causal ----------------
    _prev_c = c.groupby(level="sym").shift(1)
    _tr_s = pd.concat([hi - lo, (hi - _prev_c).abs(), (lo - _prev_c).abs()], axis=1).max(axis=1)
    _atr14 = _tr(_tr_s, lambda s: s.rolling(14).mean())
    F["natr_14"] = _atr14 / (c + 1e-9)
    F["tr_ratio"] = _tr_s / (_atr14 + 1e-9)

    ts = panel.index.get_level_values("ts")                # estacionalidad calendario
    F["dw_sin"], F["dw_cos"] = np.sin(2 * np.pi * ts.dayofweek / 7), np.cos(2 * np.pi * ts.dayofweek / 7)
    F["m_sin"], F["m_cos"] = np.sin(2 * np.pi * ts.day / 30), np.cos(2 * np.pi * ts.day / 30)
    F["mo_sin"], F["mo_cos"] = np.sin(2 * np.pi * ts.month / 12), np.cos(2 * np.pi * ts.month / 12)
    bt = F.groupby(level="ts")                             # sección cruzada (NaN-safe)
    F["mkt_ret_1"], F["mkt_ret_21"] = bt["ret_1"].transform("mean"), bt["ret_21"].transform("mean")
    F["mkt_rv_21"] = bt["lrv_21"].transform("mean")
    F["breadth_1"] = (F["ret_1"] > 0).astype(float).groupby(level="ts").transform("mean")
    F["rank_ret_21"] = bt["ret_21"].rank(pct=True)
    F["rank_rv_21"] = bt["lrv_21"].rank(pct=True)
    F["rel_ret_21"] = F["ret_21"] - F["mkt_ret_21"]
    F["rel_rv_21"] = F["lrv_21"] - F["mkt_rv_21"]
    # ---- BLOQUE SRT-CORPUS (sesión 2026-10-04, docs/srt-corpus-rules.md §2) ----
    # GARCH(1,1) + Kalman OU + Volume Profile + VWAP + SuperTrend, todo causal.
    # Se importan con try/except para que el snapshot siga siendo autocontenido.
    try:
        import sys as _sys, os as _os
        _here = _os.path.dirname(_os.path.abspath(__file__))
        for _p in (_here, _os.path.join(_os.path.dirname(_here), "quant_core")):
            if _p not in _sys.path:
                _sys.path.insert(0, _p)
        import garch_features as _G, kalman_features as _K, volume_profile as _VP
        import vwap_features as _VW, supertrend_features as _ST
        _srt = [_G.garch_block(panel["close"]), _K.kalman_block(panel["close"]),
                _VP.volume_profile_block(panel[["close", "high", "low", "volume"]]),
                _VW.vwap_block(panel[["close", "high", "low", "volume"]]),
                _ST.supertrend_block(panel[["close", "high", "low", "volume"]])]
        for _b in _srt:
            for _cc in _b.columns:
                F[_cc] = _b[_cc]
    except Exception:
        pass
    if "BTC-USD" in F.index.get_level_values("sym"):       # lead de crypto (contagio)
        b = F.xs("BTC-USD", level="sym")
        F["btc_ret_21"] = b["ret_21"].reindex(ts).to_numpy()
        F["btc_lrv_21"] = b["lrv_21"].reindex(ts).to_numpy()
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


def _live_cols(X):
    """Columnas no constantes (sklearn 1.9 crasha con constantes/degeneradas al binarizar)."""
    return [c for c in X.columns if X[c].nunique(dropna=True) > 1]


class _Model:
    """Estimador + calibración Platt (ECE bajo). Guarda las columnas válidas del fold."""
    def __init__(self, est, task, cols, platt=None):
        self.est, self.task, self.cols, self.platt = est, task, cols, platt

    def predict(self, X):
        X = X.reindex(columns=self.cols, fill_value=np.nan)
        if self.task == "vol":
            return self.est.predict(X)
        p = np.clip(self.est.predict_proba(X)[:, 1], 1e-4, 1 - 1e-4)
        if self.platt is None:
            p = 0.5 + PARAMS["shrink"] * (p - 0.5)
        else:
            p = self.platt.predict_proba(np.log(p / (1 - p)).reshape(-1, 1))[:, 1]
            p = 0.5 + PARAMS["shrink"] * (p - 0.5)
        return np.clip(p, 0.001, 0.999)


class _Const:
    def __init__(self, v, cols=None):
        self.v, self.cols = v, cols
    def predict(self, X):
        return np.full(len(X), self.v)


def fit(Xtr, ytr, task, h):
    P = PARAMS
    kw = dict(max_iter=P["max_iter"], learning_rate=P["lr"], max_depth=P["max_depth"],
              min_samples_leaf=P["min_leaf"], l2_regularization=P["l2"], random_state=0)
    if task == "vol":
        good = _live_cols(Xtr)
        est = HistGradientBoostingRegressor(**kw).fit(Xtr[good], ytr)
        return _Model(est, task, good)
    y = ytr.to_numpy()
    if y.min() == y.max():
        return _Const(float(y[0]), _live_cols(Xtr))
    if P["calib"] == "none":
        good = _live_cols(Xtr)
        return _Model(HistGradientBoostingClassifier(**kw).fit(Xtr[good], y), task, good)
    n = len(Xtr)
    a, b = int(n * 0.78), int(n * 0.80)                    # hueco cronológico entre fit y calibración
    good = _live_cols(Xtr.iloc[:a])                        # constantes en el tramo de fit => fuera
    est = HistGradientBoostingClassifier(**kw).fit(Xtr.iloc[:a][good], y[:a])
    pc = np.clip(est.predict_proba(Xtr.iloc[b:][good])[:, 1], 1e-4, 1 - 1e-4)
    platt = LogisticRegression(C=1.0).fit(np.log(pc / (1 - pc)).reshape(-1, 1), y[b:])
    return _Model(est, task, good, platt)
