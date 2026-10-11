"""market_neutral.py — ENGINE B: Market-Neutral (PCA + beta-neutral).
Extrae lo útil del diseño Quant Core v1.0 como capa de CONSTRUCCIÓN de portafolio:

1. market_factor(R): PC1 de la matriz de retornos (T×N) — factor de mercado data-driven,
   sin índice externo (clave en crypto). Normaliza signo (carga media > 0).
2. betas(R): regresión de cada activo contra PC1.
3. neutralize_weights(w, beta, gross=1.0, w_max=0.3): proyección de pesos hacia
   beta-neutral (sum w_i b_i = 0) + dollar-neutral (sum w_i = 0) con mínimos cambios,
   límite de concentración y exposición bruta fija. Para N=2 da el pairs trade.

Todo con numpy puro (sin dependencias nuevas) y determinista.
"""
import numpy as np


def market_factor(R):
    """PC1 de R (T×N). Devuelve (factor_T, loadings_N) con signo canónico."""
    R = np.nan_to_num(np.asarray(R, float), nan=0.0)
    R = R - R.mean(0, keepdims=True)
    if R.shape[0] < 10 or R.shape[1] < 2:
        return None, None
    U, S, Vt = np.linalg.svd(R, full_matrices=False)
    f = U[:, 0] * S[0]
    load = Vt[0]
    if load.mean() < 0:                                     # convención: carga media positiva
        f, load = -f, -load
    sd = f.std()
    return (f / sd if sd > 0 else f), load


def betas(R, factor=None):
    """Beta de cada columna de R contra el factor (PC1 por defecto)."""
    R = np.nan_to_num(np.asarray(R, float), nan=0.0)
    if factor is None:
        factor, _ = market_factor(R)
        if factor is None:
            return np.ones(R.shape[1])
    fm = factor - factor.mean()
    var = float(fm @ fm)
    if var <= 0:
        return np.zeros(R.shape[1])
    return (R - R.mean(0, keepdims=True)).T @ fm / var


def neutralize_weights(w, beta, gross=1.0, w_max=0.30, n_iter=60):
    """Proyecta w a beta-neutral + dollar-neutral con bruta fija. Mínimos cambios L2 con
    proyección iterativa (evita depender de un QP). Devuelve pesos finales."""
    w = np.nan_to_num(np.asarray(w, float))
    s = np.abs(w).sum()
    w = w / s * gross if s > 0 else np.zeros_like(w)
    # restricciones por proyección alternada
    for _ in range(n_iter):
        w = w - w.mean()                                    # dollar-neutral
        db = float(w @ beta)
        nb = float(beta @ beta)
        if nb > 1e-12:                                      # beta-neutral (proyección mínima)
            w = w - (db / nb) * beta
        w = np.clip(w, -w_max, w_max)                       # concentración
        br = np.abs(w).sum()
        if br > gross:                                      # bruta fija
            w *= gross / br
    return w


def turnover(prev_w, w):
    prev = np.nan_to_num(np.asarray(prev_w, float), nan=0.0)
    prev = prev[-len(w):] if len(prev) > len(w) else prev
    if len(prev) != len(w):
        return float(np.abs(w).sum())
    return float(np.abs(w - prev).sum())


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    R = rng.standard_normal((500, 6)) + 0.3 * rng.standard_normal((500, 1))  # factor común
    f, load = market_factor(R)
    b = betas(R, f)
    w = np.array([0.5, 0.4, 0.1, -0.2, -0.1, 0.0])
    wn = neutralize_weights(w, b)
    print("betas:", np.round(b, 3))
    print("w neto: sum=%.3f beta=%.3f bruta=%.3f" % (wn.sum(), wn @ b, np.abs(wn).sum()))
