"""
strategy.py — LO ÚNICO QUE EL LOOP MODIFICA (tú o un agente tipo Claude Code).
Contrato con prepare.py:
  build_features(panel) -> DataFrame con el MISMO índice que panel (MultiIndex sym, ts). SOLO info <= t.
  fit(Xtr, ytr, task, h) -> objeto con .predict(X)   (Xtr viene en orden cronológico)
     task = "dir" (prob. de retorno h>0) | "vol" (log vol horaria futura) | "exp" (prob. de expansión de vol)
Si build_features mira al futuro, prepare.py lo detecta (check_causal) y aborta.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

PARAMS = {'max_iter': 150, 'lr': 0.05, 'max_depth': 5, 'min_leaf': 200, 'l2': 1.0, 'calib': 'platt', 'timesfm': False}
SPACE = {"max_iter": [80, 150, 250, 400], "lr": [0.02, 0.03, 0.05, 0.08], "max_depth": [3, 4, 5, 6],
         "min_leaf": [100, 200, 400, 800], "l2": [0.0, 1.0, 5.0, 20.0], "calib": ["platt", "none"]}


def _tr(s, fn):
    return s.groupby(level="sym").transform(fn)


def build_features(panel):
    c, o, hi, lo, v = (panel[k] for k in ("close", "open", "high", "low", "volume"))
    lc = np.log(c)
    g = lc.groupby(level="sym")
    lr = g.diff()
    F = pd.DataFrame(index=panel.index)
    # retornos multi-horizonte (% de variación de precio)
    for k in (1, 4, 8, 12, 24, 72, 168):
        F[f"ret_{k}"] = lc - g.shift(k)
    # % de barras positivas (momentum de signo)
    up = (lr > 0).astype(float).where(lr.notna())
    for k in (12, 24, 72):
        F[f"pup_{k}"] = _tr(up, lambda s, k=k: s.rolling(k).mean())
    # anatomía de la vela: open/close/high/low
    F["body"] = (c - o) / o
    F["range"] = (hi - lo) / o
    F["close_pos"] = (c - lo) / (hi - lo + 1e-12)
    # volumen: % de variación y z-score
    lv = np.log1p(v)
    F["dvol_1"] = lv - lv.groupby(level="sym").shift(1)
    F["dvol_24"] = lv - lv.groupby(level="sym").shift(24)
    F["vol_z"] = (lv - _tr(lv, lambda s: s.rolling(168).mean())) / (_tr(lv, lambda s: s.rolling(168).std()) + 1e-9)
    # volatilidad realizada multi-escala + Parkinson + ciclo (ratios corto/largo)
    rv = {}
    for w in (6, 24, 72, 168, 720):
        rv[w] = np.log(np.sqrt(_tr(lr ** 2, lambda s, w=w: s.rolling(w).mean())) + 1e-6)
        F[f"lrv_{w}"] = rv[w]
    park = (np.log(hi / lo) ** 2) / (4 * np.log(2))
    F["lpark_24"] = np.log(np.sqrt(_tr(park, lambda s: s.rolling(24).mean())) + 1e-6)
    F["cyc_6_24"], F["cyc_24_168"], F["cyc_168_720"] = rv[6] - rv[24], rv[24] - rv[168], rv[168] - rv[720]
    F["vov_168"] = _tr(rv[24], lambda s: s.rolling(168).std())
    # ---- DESCOMPOSICIÓN DE SALTOS HAR: Bipower variation + Signed jumps causal ----
    # Barndorff-Nielsen & Shephard (2004): BP elimina saltos y aísla la difusión continua.
    abs_lr = lr.abs()
    _bp = (np.pi / 2.0) * _tr(abs_lr * _tr(abs_lr, lambda s: s.shift(1)), lambda s: s.rolling(24).mean())
    _rv24_lin = _tr(lr ** 2, lambda s: s.rolling(24).mean())
    F["jump_ratio_24"] = ((_rv24_lin - _bp) / (_rv24_lin + 1e-9)).clip(lower=0.0)
    F["lbp_24"] = np.log(np.sqrt(_bp.clip(lower=0.0)) + 1e-6)
    # semivolatilidades (asimetría de vol) + volumen firmado + flujo relativo
    up2, dn2 = lr.clip(lower=0) ** 2, (-lr).clip(lower=0) ** 2
    _pos_lin = _tr(up2, lambda s: s.rolling(24).mean())
    _neg_lin = _tr(dn2, lambda s: s.rolling(24).mean())
    F["signed_jump_24"] = (_pos_lin - _neg_lin) / (_rv24_lin + 1e-9)
    su = np.log(np.sqrt(_pos_lin) + 1e-6)
    sd = np.log(np.sqrt(_neg_lin) + 1e-6)
    F["semivol_asym_24"] = su - sd                       # vol al alza vs a la baja
    suw = np.log(np.sqrt(_tr(up2, lambda s: s.rolling(168).mean())) + 1e-6)
    sdw = np.log(np.sqrt(_tr(dn2, lambda s: s.rolling(168).mean())) + 1e-6)
    F["semivol_asym_168"] = suw - sdw
    sgn = np.sign(lr)                                    # volumen firmado acumulado (taker flow proxy)
    F["svol_24"] = _tr((sgn * lv).fillna(0), lambda s: s.rolling(24).sum())
    F["svol_72"] = _tr((sgn * lv).fillna(0), lambda s: s.rolling(72).sum())
    F["svol_z"] = F["svol_24"] / (_tr(F["svol_24"], lambda s: s.rolling(168).std()) + 1e-9)
    F["flow_imb_24"] = F["svol_24"] / (_tr(lv, lambda s: s.rolling(24).sum()) + 1e-9)
    # régimen de vol: distancia a extremos recientes (expande tras mínimo, comprime tras máximo)
    F["vmax_168"] = _tr(rv[24], lambda s: s.rolling(168).max()) - rv[24]
    F["vmin_168"] = rv[24] - _tr(rv[24], lambda s: s.rolling(168).min())
    # ---- RÉGIMEN DE VOLATILIDAD (Markov simplificado, causal) ---------------------
    # research/hidden_markov_models_for_quant_finance.ipynb: bucketizar la vol en estados
    # y modelar el retorno CONDICIONADO al estado. Aquí el estado es el z-score expansivo
    # de la vol realizada (mínimo 336h = 2 semanas), 0 = vol media.
    lm = _tr(rv[24], lambda s: s.expanding(min_periods=336).mean())
    ls = _tr(rv[24], lambda s: s.expanding(min_periods=336).std())
    reg = (rv[24] - lm) / (ls + 1e-9)
    F["reg_z"] = reg
    F["reg_hi"] = (reg > 0.5).astype("float32")                     # estado vol alta
    F["reg_lo"] = (reg < -0.5).astype("float32")                    # estado vol baja
    F["reg_persist"] = _tr(F["reg_hi"], lambda s: s.rolling(24).mean())
    # ítems de la misión §6 paso 2: momentum x ciclo de vol, y flujo x régimen
    F["mom_x_reg"] = F["pup_24"] * reg
    F["ret_x_reg"] = F["ret_24"] * reg
    F["svol_x_reg"] = F["svol_z"] * reg
    F["semivol_x_reg"] = F["semivol_asym_24"] * reg
    F["cyc_x_ret"] = F["cyc_24_168"] * F["ret_24"]
    # ---- posición del precio en su historia: drawdown, rebote, ruptura -------------
    hh720 = _tr(hi, lambda s: s.rolling(720).max())
    ll720 = _tr(lo, lambda s: s.rolling(720).min())
    F["dist_high_720"] = (c - hh720) / hh720                  # <=0: lejos del máximo 30d
    F["dist_low_720"] = (c - ll720) / ll720                   # >=0: lejos del mínimo 30d
    F["break_168"] = (c - _tr(hi, lambda s: s.rolling(168).max())) / c   # proximidad a ruptura
    F["rng_ratio"] = _tr(F["range"], lambda s: s.rolling(24).mean()) / (_tr(F["range"], lambda s: s.rolling(720).mean()) + 1e-9)
    F["skew_72"] = _tr(lr, lambda s: s.rolling(72).skew())    # momentos superiores
    F["kurt_72"] = _tr(lr, lambda s: s.rolling(72).kurt())
    F["rank_ret_72"] = F["ret_72"].groupby(level="ts").rank(pct=True)
    # ---- VWAP 24h, Garman-Klass y salto de apertura (§6 paso 1) --------------------
    tp = (hi + lo + c) / 3.0
    vwap24 = _tr(tp * v, lambda s: s.rolling(24).sum()) / (_tr(v, lambda s: s.rolling(24).sum()) + 1e-9)
    F["vwap_dist_24"] = (c - vwap24) / (vwap24 + 1e-9)
    gk = 0.5 * np.log(hi / lo) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    F["lgk_24"] = np.log(np.sqrt(_tr(gk.clip(lower=0), lambda s: s.rolling(24).mean())) + 1e-6)
    F["gap"] = np.log(o / c.groupby(level="sym").shift(1))
    F["gap_abs_24"] = _tr(F["gap"].abs(), lambda s: s.rolling(24).mean())
    # estacionalidad intradía / semanal
    ts = panel.index.get_level_values("ts")
    F["hr_sin"], F["hr_cos"] = np.sin(2 * np.pi * ts.hour / 24), np.cos(2 * np.pi * ts.hour / 24)
    F["dw_sin"], F["dw_cos"] = np.sin(2 * np.pi * ts.dayofweek / 7), np.cos(2 * np.pi * ts.dayofweek / 7)
    # sección cruzada (mercado, breadth, ranking)
    bt = F.groupby(level="ts")
    F["mkt_ret_1"], F["mkt_ret_24"] = bt["ret_1"].transform("mean"), bt["ret_24"].transform("mean")
    F["mkt_rv_24"] = bt["lrv_24"].transform("mean")
    F["breadth_1"] = (F["ret_1"] > 0).astype(float).groupby(level="ts").transform("mean")
    F["rank_ret_24"] = bt["ret_24"].rank(pct=True)
    F["rank_rv_24"] = bt["lrv_24"].rank(pct=True)
    F["rel_ret_24"] = F["ret_24"] - F["mkt_ret_24"]
    F["rel_rv_24"] = F["lrv_24"] - F["mkt_rv_24"]
    if "BTC-USDT" in F.index.get_level_values("sym"):
        b = F.xs("BTC-USDT", level="sym")
        F["btc_ret_24"] = b["ret_24"].reindex(ts).to_numpy()
        F["btc_lrv_24"] = b["lrv_24"].reindex(ts).to_numpy()
        F["btc_ret_1"] = b["ret_1"].reindex(ts).to_numpy()    # lead inmediato de BTC
        F["btc_lrv_6"] = b["lrv_6"].reindex(ts).to_numpy()
    # ---- ENGINE A (Quant Core): roughness H rodante (memoria larga) — barato en DIARIO ---
    # Se estima sobre el cierre DIARIO por símbolo (en H1 hay demasiado ruido intradía) y se
    # mapea a cada barra H1 por día (ffill causal). H<0.5 => rugoso/estresado; lo informativo
    # es la VARIACIÓN de H (z-score), no su nivel (sesgo de muestra finita). Ver quant_core/.
    # NOTA: el nº de días diarios NO puede decidir la disponibilidad de la feature (eso la
    # haría no causal frente al truncado) → se construye SIEMPRE la columna, con NaN si falta.
    import os as _os, sys as _sys
    _root = _os.path.dirname(_os.path.abspath(__file__))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from quant_core.rough_vol_lifting import rolling_roughness as _rr
    _wd = int(PARAMS.get("rough_window", 63))
    _hsyms = panel.index.get_level_values("sym").unique()
    _Hd = []
    for _sym in _hsyms:
        _d = lc.xs(_sym, level="sym").resample("1D").last().dropna()
        _Hd.append(_rr(_d, window=_wd).rename(_sym))
    _Hw = pd.concat(_Hd, axis=1)
    _tt = pd.DatetimeIndex(ts)
    _days = pd.DatetimeIndex(sorted(set(_tt.normalize())))
    # LAG de 1 día: el H de la barra en el día D usa el último día COMPLETO anterior a D.
    # Sin esto, el cierre diario del propio día D (barra 23:00) informaría a las barras
    # tempranas de D => look-ahead (lo detecta check_causal). Con el lag es estrictamente causal.
    _grid = pd.date_range(min(_days.min(), _Hw.index.min()), _days.max(), freq="D")
    _Hw = _Hw.reindex(_grid).ffill().shift(1).reindex(_days).ffill()
    _key = pd.MultiIndex.from_arrays([_tt.normalize(), panel.index.get_level_values("sym")])
    if len(_Hw):
        Hh = pd.Series(_Hw.stack().reindex(_key).to_numpy(), index=panel.index)
    else:
        Hh = pd.Series(np.nan, index=panel.index)
    F["rough_H"] = Hh
    _hm = Hh.groupby(level="sym").transform(lambda s: s.rolling(24 * 252, min_periods=24 * 63).mean())
    _hsd = Hh.groupby(level="sym").transform(lambda s: s.rolling(24 * 252, min_periods=24 * 63).std())
    F["rough_H_z"] = (Hh - _hm) / (_hsd + 1e-9)
    F["rough_regime"] = (Hh < _hm - 0.5 * _hsd).astype("float32")
    F["rough_H_rank"] = Hh.groupby(level="ts").rank(pct=True)
    if PARAMS["timesfm"]:
        F = F.join(timesfm_features(panel))
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


def timesfm_features(panel, ctx=512, stride=4, horizons=(1, 4, 8, 12, 24)):
    """OPCIONAL (NO probado en este entorno: requiere GPU + pesos TimesFM-3, licencia NO comercial).
    Cuantiles zero-shot de TimesFM-3 sobre log-precio normalizado -> features tfm_med_h / tfm_spread_h."""
    from timesfm3 import TimesFM3Evaluator, ModelConfig      # API del README de google-research/timesfm
    fc = TimesFM3Evaluator(ModelConfig(checkpoint_path="google/timesfm-3.0-pytorch", per_core_batch_size=64, device="cuda"))
    H = max(horizons)
    cols = [f"tfm_{k}_{hz}" for hz in horizons for k in ("med", "spread")]
    out = np.full((len(panel), len(cols)), np.nan, np.float32)
    lc = np.log(panel["close"]).to_numpy()
    hour = panel.index.get_level_values("ts").values.astype("datetime64[h]").astype(np.int64)
    for sym, idx in panel.groupby(level="sym").indices.items():
        x, hh = lc[idx], hour[idx]
        pos = [i for i in range(ctx, len(x)) if hh[i] % stride == 0 and not np.isnan(x[i - ctx + 1:i + 1]).any()]
        ctxs = [(x[i - ctx + 1:i + 1] - x[i]).astype(np.float32) for i in pos]
        for b in range(0, len(ctxs), 512):
            for j, r in enumerate(fc.predict_batch(ctxs[b:b + 512], horizon=H, return_quantiles=True,
                                                   use_symmetric_averaging=False)):
                q = r.quantiles                                     # (H, 9): deciles 0.1..0.9
                row = idx[pos[b + j]]
                for k, hz in enumerate(horizons):
                    out[row, 2 * k], out[row, 2 * k + 1] = q[hz - 1, 4], q[hz - 1, 8] - q[hz - 1, 0]
    df = pd.DataFrame(out, index=panel.index, columns=cols)
    return df.groupby(level="sym").ffill(limit=stride - 1)          # solo rellena hacia adelante (causal)


class _Model:
    """Regresor/Clasificador + calibración Platt (recalibra probabilidades = ECE bajo)."""
    def __init__(self, est, task, platt=None):
        self.est, self.task, self.platt = est, task, platt

    def predict(self, X):
        if self.task == "vol":
            return self.est.predict(X)
        p = np.clip(self.est.predict_proba(X)[:, 1], 1e-4, 1 - 1e-4)
        if self.platt is None:
            return p
        return np.clip(self.platt.predict_proba(np.log(p / (1 - p)).reshape(-1, 1))[:, 1], 0.001, 0.999)


class _Const:
    def __init__(self, v): self.v = v
    def predict(self, X): return np.full(len(X), self.v)


def fit(Xtr, ytr, task, h):
    P = PARAMS
    kw = dict(max_iter=P["max_iter"], learning_rate=P["lr"], max_depth=P["max_depth"],
              min_samples_leaf=P["min_leaf"], l2_regularization=P["l2"], random_state=0)
    if task == "vol":
        return _Model(HistGradientBoostingRegressor(**kw).fit(Xtr, ytr), task)
    y = ytr.to_numpy()
    if y.min() == y.max():
        return _Const(float(y[0]))
    if P["calib"] == "none":
        return _Model(HistGradientBoostingClassifier(**kw).fit(Xtr, y), task)
    n = len(Xtr)
    a, b = int(n * 0.78), int(n * 0.80)                            # hueco cronológico entre fit y calibración
    est = HistGradientBoostingClassifier(**kw).fit(Xtr.iloc[:a], y[:a])
    pc = np.clip(est.predict_proba(Xtr.iloc[b:])[:, 1], 1e-4, 1 - 1e-4)
    platt = LogisticRegression(C=1.0).fit(np.log(pc / (1 - pc)).reshape(-1, 1), y[b:])
    return _Model(est, task, platt)
