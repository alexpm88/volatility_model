"""
__main__.py — Punto de entrada del motor de carteras.
   python3 -m portfolio_engine [--refrescar] [--validar] [capital] [top_k] [vol_target]
Ejemplos:
   python3 -m portfolio_engine --refrescar 100000 20 0.10     # backtest + reporte
   python3 -m portfolio_engine --validar                      # folds + placebo + sensibilidad
   python3 -m portfolio_engine --validar --cost-bps 10        # robustez a 10 bps/lado
   python3 -m portfolio_engine --validar --cost-bps 10 --universe 40   # + 40 nombres
"""

import sys

from .backtester import PortfolioBacktester
from .data_loader import load_or_fetch_universe, DEFAULT_UNIVERSE_40


def _flag_val(argv, name, default=None):
    """Valor de un flag --name=VAL (o --name VAL); ``default`` si ausente."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--refrescar" in argv
    nums = [a for a in argv if not a.startswith("-")]

    capital = float(nums[0]) if len(nums) > 0 else 100000.0
    top_k = int(nums[1]) if len(nums) > 1 else 20
    target_vol = float(nums[2]) if len(nums) > 2 else 0.10

    # Flags opcionales de robustez (P5.1): --cost-bps=N (costo por lado) y
    # --universe=N (25 = default, 40 = DEFAULT_UNIVERSE_40). Backward compatible.
    cost_bps = float(_flag_val(argv, "--cost-bps", "5.0"))
    universe_n = int(_flag_val(argv, "--universe", "25"))
    symbols = DEFAULT_UNIVERSE_40 if universe_n == 40 else None
    pkg = load_or_fetch_universe(symbols=symbols, force_refresh=force)

    if "--validar" in argv:
        from .validation import validate
        validate(pkg["panel"], commission_bps=cost_bps)
        return None

    bt = PortfolioBacktester(pkg["panel"], initial_capital=capital, commission_bps=cost_bps,
                             top_k=top_k, rebalance_freq=21, target_vol=target_vol)
    bt.run()
    bt.report()
    out = bt.save_report()
    print("reporte guardado en:", out)
    return bt


if __name__ == "__main__":
    main()
