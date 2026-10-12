"""
backtester.py - Motor de simulación y contabilidad cuantitativa de carteras dinámicas.
Características:
- Saldo inicial configurable y fecha de inicio configurable
- Rebalanceo periódico (e.g. mensual / 21 días de trading)
- Selección rotativa de las Top K acciones del mes
- Cobro exacto de dividendos en fechas ex-dividend / de pago
- Reinversión automática del flujo de caja (dividendo y ventas)
- Modelado de comisiones y slippage (e.g. 5 bps por lado)
- Dynamic Volatility Target Scaling (Risk Parity / Vol Target e.g. 10%)
- Reporte detallado día a día de NAV, Cash, Holdings, Dividendos y Métricas de Rendimiento

Contabilidad por ACCIONES (no por pesos): así el flujo de dividendos se cobra sobre la posición
realmente mantenida. Causalidad estricta: en el cierre de la fecha d se decide con información
<= d y esa posición es la que devenga el retorno de d -> d+1 (ningún dato futuro entra al peso).
"""

import json
import os

import numpy as np
import pandas as pd

from .optimizer import compute_inverse_vol_weights
from .signals import compute_asset_features, rank_and_select_top_k


class PortfolioBacktester:
    def __init__(self, panel, initial_capital=100000.0, commission_bps=5.0, top_k=None,
                 rebalance_freq=21, target_vol=0.10, max_stock_weight=0.08,
                                                                    slippage_bps=0.0, max_leverage=1.0, vol_lookback=63, min_history=126,
                 regime_filter=False, regime_window=200, regime_series=None,
                 regime_trigger="ma200", regime_k=1.5,
                 regime_volume_series=None):
        self.raw_panel = panel
        self.initial_capital = float(initial_capital)
        self.commission_rate = (float(commission_bps) + float(slippage_bps)) / 10000.0
        self.top_k = None if top_k is None else int(top_k)   # P5.7: None = full-breadth (sin truncar)
        self.rebalance_freq = int(rebalance_freq)
        self.target_vol = float(target_vol)
        self.max_stock_weight = float(max_stock_weight)
        self.max_leverage = float(max_leverage)
        self.vol_lookback = int(vol_lookback)
        self.min_history = int(min_history)
        # Filtro de régimen (P5.2): en régimen bajista (regime_series close < MA(regime_window))
        # pasa a efectivo para recortar beta. Causal (la MA solo usa precios <= date).
        # Default False => comportamiento idéntico al original (backward compatible).
        self.regime_filter = bool(regime_filter)
        self.regime_window = int(regime_window)
        self._regime_close = regime_series
        self._regime_volume = regime_volume_series
        self.regime_trigger = regime_trigger
        self.regime_k = float(regime_k)
        self._regime_ma = None
        self._regime_vol = None
        self._regime_acc_dist = None  # P5.9: acc_dist regime mask

        # Precomputar features causales (todo rolling hacia atrás => sin look-ahead)
        print("[Backtester] Calculando señales multifactoriales causales...")
        self.df = compute_asset_features(panel)
        self.dates = sorted(self.df.index.get_level_values("date").unique())
        self.symbols = sorted(self.df.index.get_level_values("symbol").unique())
        self.history = pd.DataFrame()
        self.trades = pd.DataFrame()

    # ------------------------------------------------------------------ utilidades
    def _price_matrix(self):
        """Matriz fecha x símbolo de precios de cierre (índice de fechas ordenado)."""
        return self.df["close"].unstack("symbol").sort_index()

    def _rebalance_dates(self):
        """Fechas de rebalanceo: cada `rebalance_freq` días, una vez cubierta la historia mínima."""
        return {d for i, d in enumerate(self.dates)
                if i >= self.min_history and (i - self.min_history) % self.rebalance_freq == 0}

    def _in_bear_regime(self, date):
        """True si el filtro de régimen está activo y el mercado (regime_series, p.ej. SPY) está
        en régimen de riesgo => ir a efectivo (recortar beta). Causal (sólo info <= date).
        - trigger 'ma200' (P5.2): close < MA(regime_window).
        - trigger 'vol_spike' (P5.4): rv21 > k·rv126 (spike de vol; libera cash al normalizarse).
        - trigger 'acc_dist' (P5.9): distribución cuando price↓ + volume↑ (smart money out) => cash;
          acumulación cuando price↑ + volume↑ (smart money in) => stay invested. Usa cross-sectional
          median close/volume del panel como proxy de mercado (o regime_series/regime_volume_series)."""
        if not self.regime_filter:
            return False
        # acc_dist trigger computes market proxy cross-sectionally (no _regime_close needed)
        if self.regime_trigger == "acc_dist":
            if self._regime_acc_dist is None:
                mc = self._regime_close if self._regime_close is not None else \
                    self.df["close"].groupby(level="date").median()
                mv = self._regime_volume if self._regime_volume is not None else \
                    self.df["volume"].groupby(level="date").median()
                market_ma = mc.rolling(self.regime_window).mean()
                vol_ma = mv.rolling(self.regime_window).mean()
                vol_std = mv.rolling(self.regime_window).std()
                # Distribution: price below MA (falling) + volume above avg+k*std (rising)
                # => smart money distributing => bear regime (cash)
                self._regime_acc_dist = (mc < market_ma) & (mv > vol_ma + self.regime_k * vol_std)
            return bool(self._regime_acc_dist.get(date, False))
        if self._regime_close is None:
            return False
        rc = self._regime_close
        if self._regime_ma is None and self._regime_vol is None:
            if self.regime_trigger == "vol_spike":
                r = np.log(rc / rc.shift(1))
                rv21 = r.rolling(21).std() * np.sqrt(252)        # vol corta (21d anualizada)
                rv126 = r.rolling(126).std() * np.sqrt(252)      # vol larga / baseline
                self._regime_vol = (rv21 > self.regime_k * rv126)
            else:                                              # 'ma200' (backward compatible)
                self._regime_ma = rc.rolling(self.regime_window).mean()
        if self.regime_trigger == "vol_spike":
            return bool(self._regime_vol.get(date, False))
        ma = self._regime_ma.get(date, default=np.nan)
        cl = self._regime_close.get(date, default=np.nan)
        return bool(np.isfinite(cl) and np.isfinite(ma) and cl < ma)

    def _target_weights(self, date):
        """Pesos objetivo (fracción del NAV) usando SOLO información disponible en `date`.
        Devuelve (pesos, vol_de_cartera_estimada, apalancamiento_aplicado)."""
        if self._in_bear_regime(date):
            return pd.Series(dtype=float), float("nan"), 0.0   # régimen bajista => cash
        names = rank_and_select_top_k(self.df, date, top_k=self.top_k, min_history=self.min_history)
        if not names:
            return pd.Series(dtype=float), float("nan"), 0.0
        rv = self.df.xs(date, level="date")["rv63"].reindex(names).dropna()
        if rv.empty:
            return pd.Series(dtype=float), float("nan"), 0.0
        w = compute_inverse_vol_weights(rv, max_weight=self.max_stock_weight)
        names = list(w.index)
        # Sigma de los últimos `vol_lookback` días (solo pasado) para el vol targeting
        hist = self.df["lr"].unstack("symbol").loc[:date].tail(self.vol_lookback).reindex(columns=names)
        if hist.shape[1] > 1 and hist.shape[0] > 2:
            cov = hist.cov().values * 252.0
            v = w.values
            port_vol = float(np.sqrt(max(v @ cov @ v, 0.0)))
        else:
            port_vol = float((w * rv).sum())
        if not np.isfinite(port_vol) or port_vol <= 0:
            return pd.Series(dtype=float), port_vol, 0.0
        lev = float(np.clip(self.target_vol / port_vol, 0.0, self.max_leverage))
        return w * lev, port_vol, lev

    # ------------------------------------------------------------------ simulación
    def run(self):
        """Simula la cartera día a día: dividendos, rebalanceo, costos, NAV y cash."""
        px = self._price_matrix()
        div = self.df["dividend"].unstack("symbol").reindex(columns=self.symbols).fillna(0.0)
        rebal = self._rebalance_dates()
        shares = pd.Series(0.0, index=self.symbols)
        cash = self.initial_capital
        rows, trades = [], []

        for d in self.dates:
            p = px.loc[d].reindex(self.symbols)            # precio de cierre de HOY
            pt = p.fillna(0.0)                             # solo contabilidad (panel sin NaNs)
            # 1) Dividendo del día sobre las acciones del cierre previo (ex-dividend date)
            div_flow = float((shares * div.loc[d]).sum())
            cash += div_flow
            # 2) Marcar a mercado con el cierre del día
            holdings = float((shares * pt).sum())
            nav = cash + holdings
            # 3) Rebalanceo al cierre de d: la posición nueva devenga el retorno de d -> d+1
            comm = turnover = 0.0
            if d in rebal and nav > 0:
                w, port_vol, lev = self._target_weights(d)
                w = w[w.index.isin(p[p.notna()].index)]    # no operar activos sin precio ese día
                if len(w) and float(w.sum()) > 0:
                    tgt = (nav * w / p.reindex(w.index)).reindex(self.symbols).fillna(0.0)
                    delta = tgt - shares
                    traded_value = float((delta.abs() * pt).sum())
                    comm = traded_value * self.commission_rate
                    cash -= float((delta * pt).sum()) + comm      # reinversión automática del cash
                    turnover = traded_value / nav
                    trades.append(dict(date=d, n_positions=len(w), port_vol=port_vol,
                                       leverage=lev, turnover=turnover, cost=comm))
                    shares = tgt
                    holdings = float((shares * pt).sum())
                    nav = cash + holdings
            rows.append(dict(date=d, nav=nav, cash=cash, holdings=holdings, dividend=div_flow,
                             commission=comm, turnover=turnover,
                             n_positions=int((shares.abs() > 1e-9).sum())))
        self.history = pd.DataFrame(rows).set_index("date")
        self.trades = pd.DataFrame(trades).set_index("date") if trades else pd.DataFrame()
        return self.history

    # ------------------------------------------------------------------ métricas
    def metrics(self):
        """Métricas de rendimiento y contabilidad agregada del backtest."""
        if self.history.empty:
            return {}
        nav = self.history["nav"]
        ret = (nav / nav.shift(1) - 1.0).dropna()
        years = len(nav) / 252.0
        total_return = float(nav.iloc[-1] / self.initial_capital - 1.0)
        cagr = float((nav.iloc[-1] / self.initial_capital) ** (1.0 / years) - 1.0) if years > 0 else float("nan")
        vol = float(ret.std() * np.sqrt(252)) if len(ret) > 1 else float("nan")
        sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if len(ret) > 1 and ret.std() > 0 else float("nan")
        mdd = float((nav / nav.cummax() - 1.0).min())
        return dict(initial_capital=self.initial_capital, final_nav=float(nav.iloc[-1]),
                    total_return=total_return, cagr=cagr, ann_vol=vol, sharpe=sharpe,
                    max_drawdown=mdd, calmar=(cagr / abs(mdd)) if mdd < 0 else float("nan"),
                    total_dividends=float(self.history["dividend"].sum()),
                    total_costs=float(self.history["commission"].sum()),
                    avg_daily_turnover=float(self.history["turnover"].mean()),
                    n_rebalances=int(len(self.trades)), days=int(len(nav)),
                    avg_positions=float(self.history["n_positions"].mean()))

    def report(self):
        """Imprime el resumen de rendimiento y devuelve el dict de métricas."""
        m = self.metrics()
        if not m:
            print("[Backtester] sin resultados: llama a run() antes de report()")
            return {}
        print("\n=== PORTFOLIO ENGINE | cartera long-only multifactorial con dividendos ===")
        print(f"periodo            {self.dates[0].date()} -> {self.dates[-1].date()}  ({m['days']} días)")
        print(f"capital inicial    {m['initial_capital']:,.0f}  ->  NAV final {m['final_nav']:,.0f}")
        print(f"retorno total      {m['total_return']:+.2%}   CAGR {m['cagr']:+.2%}   vol anual {m['ann_vol']:.2%}")
        print(f"sharpe             {m['sharpe']:+.2f}   max drawdown {m['max_drawdown']:.2%}   calmar {m['calmar']:+.2f}")
        print(f"dividendos         {m['total_dividends']:,.0f}   costos {m['total_costs']:,.0f}"
              f"   turnover diario {m['avg_daily_turnover']:.2%}")
        print(f"rebalanceos        {m['n_rebalances']}   posiciones medias {m['avg_positions']:.1f}")
        return m

    def save_report(self, outdir=None):
        """Guarda el detalle día a día (.tsv) y las métricas (.json) según convenciones del repo."""
        outdir = outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(outdir, exist_ok=True)
        self.history.to_csv(os.path.join(outdir, "nav_daily.tsv"), sep="\t")
        with open(os.path.join(outdir, "metrics.json"), "w") as f:
            json.dump(self.metrics(), f, indent=1, default=str)
        if not self.trades.empty:
            self.trades.to_csv(os.path.join(outdir, "rebalances.tsv"), sep="\t")
        return outdir
