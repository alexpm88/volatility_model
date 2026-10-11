"""rough_vol_lifting.py — ENGINE A: Rough Volatility vía Markovian Lifting.
1. fit_exponential_kernel(H, n, T): aproxima K_H(t)=t^(H-1/2)/Gamma(H+1/2) como
   suma de exponenciales c_i·exp(-x_i t) (Abi Jaber-El Euch / Bayer-Breneis).
2. LiftedRoughState: simula n factores OU + varianza rough (Euler, O(n)/paso).
3. implied_vol_from_price (Black-76, agnóstico a activo).
4. calibrate_skew: ajusta (H, eta, rho) a un skew observado.
5. benchmark_lifting: O(n) lifting vs convolución fraccionaria O(N^2).
6. rolling_roughness: H proxy RODANTE y CAUSAL (solo datos <= t) como feature
   para strategy.py / strategy_multi.py. H bajo = régimen rugoso/estresado.
"""
import numpy as np
from math import lgamma


# ------------------------------------------------------------------ kernel lifting
def fit_exponential_kernel(H, n_factors=8, T=1.0, n_grid=400):
    """Devuelve (c_i, x_i, err) que aproximan K_H(t) en [0,T] por mínimos cuadrados."""
    assert 0.05 < H < 0.5, "H debe estar en (0.05, 0.5) para rough vol"
    t = np.linspace(1e-4, T, n_grid)
    K = np.exp((H - 0.5) * np.log(t) - lgamma(H + 0.5))
    xs = np.exp(np.linspace(np.log(1.0 / T), np.log(1.0 / 1e-4), n_factors))
    A = np.exp(-np.outer(t, xs))
    c, *_ = np.linalg.lstsq(A, K, rcond=None)
    err = float(np.sqrt(np.mean((A @ c - K) ** 2)))
    return c, xs, err


class LiftedRoughState:
    """Sistema Markoviano liftado: V_t = xi0(t)·exp(eta·sum_i c_i Y_i - 0.5 eta^2 Var),
    dY_i = -x_i Y_i dt + dW_i (W independientes; la correlación rho se aplica al precio)."""

    def __init__(self, H, eta=0.3, n_factors=8, T=1.0, seed=0):
        self.c, self.x, self.err = fit_exponential_kernel(H, n_factors, T)
        self.H, self.eta, self.T, self.rng = H, eta, T, np.random.default_rng(seed)

    def var_term(self, n_steps):
        t = np.linspace(1e-4, self.T, n_steps)
        V = sum((ci ** 2) * (1 - np.exp(-2 * xi * t)) / (2 * xi) for ci, xi in zip(self.c, self.x))
        return t, V

    def simulate_variance(self, n_paths=1000, n_steps=252, xi0=0.04):
        t, V = self.var_term(n_steps)
        dt = np.diff(t, prepend=0.0)
        Y = np.zeros((n_paths, len(self.x)))
        Vp = np.zeros((n_paths, n_steps))
        for k in range(1, n_steps):
            dW = self.rng.standard_normal((n_paths, len(self.x))) * np.sqrt(dt[k])
            Y = Y * np.exp(-self.x * dt[k]) + dW            # Euler exacto para OU
            Vp[:, k] = Y @ self.c
        sig = np.sqrt(xi0) * np.exp(self.eta * (Vp - 0.5 * self.eta * V))
        return t, sig

    def simulate_paths(self, S0=100.0, rho=-0.3, mu=0.0, n_paths=1000, n_steps=252, xi0=0.04):
        """Precio + varianza con Browniano correlacionado (rho). Devuelve (t, S, sig)."""
        t, sig = self.simulate_variance(n_paths, n_steps, xi0)
        dt = np.diff(t, prepend=0.0)
        rng = self.rng
        z1 = rng.standard_normal((n_paths, n_steps))
        z2 = rng.standard_normal((n_paths, n_steps))
        dWv = z1 * np.sqrt(dt)
        dWs = (rho * z1 + np.sqrt(1 - rho ** 2) * z2) * np.sqrt(dt)
        logS = np.cumsum((mu - 0.5 * sig ** 2) * dt + sig * dWs, axis=1)
        S = S0 * np.exp(logS)
        return t, S, sig


def price_european_mc(paths, K, T, r=0.0, is_call=True, S0=None):
    """Precio Monte Carlo de una opción europea desde paths de precio (n_paths, n_steps).
    Devuelve dict(price, stderr, n_paths). r = tasa libre de riesgo (0 para crypto funding).

    - `paths`: matriz (n_paths, n_steps) de precios simulados (p.ej. de simulate_paths()[1]).
    - El descuento se aplica sobre el payoff esperado al vencimiento (último paso).
    """
    P = np.asarray(paths, dtype=float)
    if P.ndim != 2:
        raise ValueError("paths debe ser (n_paths, n_steps)")
    ST = P[:, -1]
    payoff = np.maximum(ST - K, 0.0) if is_call else np.maximum(K - ST, 0.0)
    disc = np.exp(-r * T)
    price = disc * float(payoff.mean())
    stderr = disc * float(payoff.std(ddof=1) / np.sqrt(len(payoff))) if len(payoff) > 1 else float("nan")
    return dict(price=price, stderr=stderr, n_paths=int(len(payoff)))


def implied_vol_from_price(price, F, K, T, is_call=True, lo=1e-3, hi=5.0):
    """Inversión por bisección de Black-76 (forward F)."""
    from math import log, sqrt, erf
    N = lambda x: 0.5 * (1.0 + erf(x / sqrt(2.0)))          # noqa: E731

    def black76(s):
        d1 = (log(F / K) + 0.5 * s * s * T) / (s * sqrt(T))
        d2 = d1 - s * sqrt(T)
        return F * N(d1) - K * N(d2) if is_call else K * N(-d2) - F * N(-d1)

    a, b = lo, hi
    for _ in range(60):
        m = 0.5 * (a + b)
        if black76(m) > price:
            b = m
        else:
            a = m
    return 0.5 * (a + b)



def calibrate_skew(strikes, ivs, T, n_factors=6, H0=0.15):
    """Ajusta (H, eta, rho) al skew observado (un tenor). Skew modelo: eta·rho·sqrt(2H)·log(K/F)."""
    from scipy.optimize import least_squares
    strikes, ivs = np.asarray(strikes, float), np.asarray(ivs, float)
    F = float(np.median(strikes))

    def resid(p):
        H, eta, rho = p
        if not (0.06 < H < 0.49 and 0.02 < eta < 2.0 and -0.99 < rho < 0.99):
            return np.full(len(strikes), 10.0)
        model = np.median(ivs) + eta * rho * np.sqrt(2 * H) * np.log(strikes / F)
        return model - ivs

    out = least_squares(resid, x0=[H0, 0.5, -0.3], bounds=([0.06, 0.02, -0.99], [0.49, 2.0, 0.99]))
    return dict(H=float(out.x[0]), eta=float(out.x[1]), rho=float(out.x[2]),
                rmse=float(np.sqrt(np.mean(out.fun ** 2))))


def benchmark_lifting(H=0.1, n_factors=8, T=1.0, n_steps=504, n_paths=50):
    """O(n) lifting vs convolución fraccionaria O(N^2) para n_paths paths."""
    import time
    st = LiftedRoughState(H, 0.3, n_factors, T, seed=0)
    t0 = time.perf_counter(); st.simulate_variance(n_paths, n_steps); t_lift = time.perf_counter() - t0
    K = np.exp((H - 0.5) * np.log(np.linspace(1e-4, T, n_steps)) - lgamma(H + 0.5))
    dW = np.random.default_rng(0).standard_normal((n_paths, n_steps)) / np.sqrt(n_steps)
    t0 = time.perf_counter()
    for p in range(n_paths):                                # convolución completa por path
        for k in range(n_steps):
            _ = float(K[:k + 1][::-1] @ dW[p, :k + 1])
    t_naive = time.perf_counter() - t0
    return t_lift, t_naive, t_naive / max(t_lift, 1e-9)


# ---------------------------------------------------------- feature causal (H rodante)
def rolling_roughness(r_log, window=126, lags=(1, 2, 3, 5, 8, 13, 21)):
    """Hurst rodante por regresión log(vol incremental)-vs-log(lag) sobre el CAMINO
    (niveles del log-precio). CAUSAL: solo usa datos <= t.
    NOTA: el estimador está sesgado hacia abajo en muestras finitas (R/S clásico);
    lo informativo como feature es la VARIACIÓN de H, no su nivel absoluto.
    H bajo relativo = régimen rugoso/estresado; H alto relativo = calmo/tendencial."""
    import pandas as pd
    x = np.log(np.array(lags, dtype=float))
    X = np.c_[np.ones(len(x)), x]

    def hurst(win):
        v = np.asarray(win, float)
        if np.allclose(v, v[0]):
            return np.nan
        ys = []
        for L in lags:
            d = v[L:] - v[:-L]
            s = d.std()
            ys.append(np.log(s + 1e-12) if s > 1e-12 else np.nan)
        ys = np.array(ys, float)
        ok = np.isfinite(ys)
        if ok.sum() < 3:
            return np.nan
        return float(np.linalg.lstsq(X[ok], ys[ok], rcond=None)[0][1])

    return pd.Series(r_log).astype(float).rolling(window).apply(hurst, raw=True)


if __name__ == "__main__":
    c, xs, err = fit_exponential_kernel(0.10, 8, 1.0)
    print(f"kernel fit RMS err = {err:.2e} (8 factores)")
    tl, tn, ratio = benchmark_lifting()
    print(f"lifting O(n)={tl*1000:.1f}ms vs convolucion O(N^2)={tn*1000:.1f}ms speedup~{ratio:.1f}x")
    import pandas as pd
    rng = np.random.default_rng(1)
    # Hurst sobre NIVELES del camino (log-precio), no sobre retornos.
    # Muestra grande (20k) para mostrar convergencia; con 2k el sesgo de muestra finita
    # sesga H hacia abajo (por eso en la estrategia se usa la VARIACIÓN de H, no su nivel).
    h = rolling_roughness(np.cumsum(rng.standard_normal(20000)), 126).dropna()
    print(f"H camino Browniano, 20k obs (esperado ~0.5): {h.iloc[-1]:.3f}")
    rr = np.cumsum(rng.choice([1, 3], p=[.8, .2], size=20000) * rng.standard_normal(20000))
    h2 = rolling_roughness(rr, 126).dropna()
    print(f"H serie con volatilidad intermitente, 20k obs (esperado <0.5): {h2.iloc[-1]:.3f}")
