"""
portfolio_engine — Motor de carteras cuantitativas de RENTA VARIABLE con dividendos explícitos.
Pipeline causal: data_loader (Yahoo, caché .pkl) -> signals (features multifactoriales + ranking
cross-seccional) -> optimizer (inverse-vol / mínima varianza con tope de concentración) ->
backtester (rebalanceo periódico, cobro de dividendos, costos y vol targeting).

Uso:  python3 -m portfolio_engine
"""

from .data_loader import DEFAULT_UNIVERSE, load_or_fetch_universe
from .signals import compute_asset_features, rank_and_select_top_k
from .optimizer import compute_inverse_vol_weights, compute_minimum_variance_weights
from .backtester import PortfolioBacktester

__all__ = [
    "DEFAULT_UNIVERSE",
    "load_or_fetch_universe",
    "compute_asset_features",
    "rank_and_select_top_k",
    "compute_inverse_vol_weights",
    "compute_minimum_variance_weights",
    "PortfolioBacktester",
]
