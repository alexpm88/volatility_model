"""
optimizer.py - Construcción y optimización de carteras cuantitativas.
Modelos soportados:
- Inverse Volatility (Risk-Weighted Parity)
- Equal-Weight
- Maximum Diversification / Minimum Variance
Con constraints estrictos de concentración máxima (e.g. max 8% por activo).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

def compute_inverse_vol_weights(rv_series, max_weight=0.08):
    """
    Ponderación por inversa de volatilidad con tope de concentración.
    w_i = (1 / sigma_i) / sum(1 / sigma_j)
    """
    inv_vol = 1.0 / (rv_series + 1e-4)
    w = inv_vol / inv_vol.sum()
    
    # Aplicar constraint de concentración máxima de forma iterativa
    for _ in range(10):
        excess = np.maximum(0, w - max_weight)
        if excess.sum() == 0:
            break
        w = np.minimum(w, max_weight)
        # Redistribuir exceso entre los que no han llegado al tope
        non_capped = w < (max_weight - 1e-5)
        if non_capped.sum() > 0:
            w[non_capped] += excess.sum() * (w[non_capped] / w[non_capped].sum())
        else:
            break
            
    # Normalizar para asegurar suma exacta a 1.0
    w = w / w.sum()
    return pd.Series(w, index=rv_series.index)

def compute_minimum_variance_weights(cov_matrix, max_weight=0.08):
    """
    Optimización cuadrática de Mínima Varianza sujeta a:
    min w^T Cov w
    s.t. sum(w) = 1, 0 <= w_i <= max_weight
    """
    n = len(cov_matrix)
    if n == 0:
        return pd.Series(dtype=float)
    if n == 1:
        return pd.Series([1.0], index=cov_matrix.index)
        
    init_w = np.ones(n) / n
    bounds = [(0.0, max_weight) for _ in range(n)]
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    
    def port_var(w):
        return np.dot(w.T, np.dot(cov_matrix.values, w))
        
    res = minimize(port_var, init_w, method='SLSQP', bounds=bounds, constraints=constraints)
    if res.success:
        return pd.Series(res.x, index=cov_matrix.index)
    else:
        # Fallback a equal weight
        return pd.Series(init_w, index=cov_matrix.index)
