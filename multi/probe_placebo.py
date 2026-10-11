import numpy as np, pandas as pd, sys
sys.path.insert(0, '/run/media/perh2x/Projectos/volatility_model')
sys.path.insert(0, '/run/media/perh2x/Projectos/volatility_model/multi')
from prepare_multi import backtest_ls, load_panel, load_universe

panel = load_panel(); cls_map, cost_map = load_universe()
ts = panel.index.get_level_values('ts'); syms = panel.index.get_level_values('sym')
tmin = np.datetime64(ts.min(), 'D')
hidx = ((ts.values.astype('datetime64[D]') - tmin).astype('timedelta64[D]').astype(np.int64))
uts = np.sort(ts.unique()); cut = uts[int(len(uts) * 0.8)]
cut_d = int((np.datetime64(cut, 'D') - tmin).astype('timedelta64[D]').astype(np.int64))
base = (hidx >= 756) & (hidx < cut_d)
costs = pd.Series(np.asarray(syms), index=panel.index).map(cost_map).to_numpy()
h = 10
m = base & (hidx % h == 0)
r = panel['close'].groupby(level='sym').apply(lambda s: np.log(s).diff(-h).shift(0))  # no usado
# retorno h: log(c_{t+h}) - log(c_t) por sym
lc = np.log(panel['close'])
rr = lc.groupby(level='sym').shift(-h) - lc
r = rr.to_numpy()

# p ESTRUCTURADO: ranking fijo de syms + ruido pequeño (un modelo "real" típico)
sym_rank = pd.Series(np.asarray(syms)).map({s: i for i, s in enumerate(sorted(set(syms)))}).to_numpy()
rng0 = np.random.default_rng(7)
p_struct = pd.Series(0.5 + 0.02 * sym_rank + 0.002 * rng0.standard_normal(len(panel)), index=panel.index).where(m).to_numpy()

bt_real, _ = backtest_ls(p_struct[m], r[m], ts[m], syms[m], costs[m], h)
print(f'p_estructurado REAL: netSharpe={bt_real["net_sharpe"]:+.2f} n={bt_real["n"]}')

shs = []
for sd_ in range(8):
    rng = np.random.default_rng(sd_)
    pp = pd.Series(p_struct[m]).groupby(ts[m].to_numpy()).transform(
        lambda x: rng.permutation(x.to_numpy())).to_numpy()
    if sd_ == 0:
        same = np.allclose(pp[~np.isnan(pp)], p_struct[m][~np.isnan(pp)])
        print(f'  permuta cambio el vector? {"NO (BUG!)" if same else "sí"}')
    bt_p, _ = backtest_ls(pp, r[m], ts[m], syms[m], costs[m], h)
    shs.append(bt_p['net_sharpe'])
shs = np.array(shs)
print(f'p_estructurado PLACEBO: media={shs.mean():+.2f} sd={shs.std():.2f} max={shs.max():+.2f}')
print('PROBE2_DONE')

# --- verificacion: que hace transform(perm) en pandas 3.0?
x = pd.Series([10, 20, 30, 40], index=['a', 'b', 'c', 'd'])
g = pd.Series(['g1', 'g1', 'g1', 'g1'])
out = x.groupby(g).transform(lambda a: np.random.default_rng(0).permutation(a.to_numpy()))
print('transform-perm test:', out.to_dict(), ' (esperado: mismo conjunto {10,20,30,40} reordenado)')

