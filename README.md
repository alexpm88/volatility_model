# Volatility Lab — KuCoin top-50 H1 (loop estilo Karpathy)

Pipeline completo: datos → features → modelo → validación → loop de mejora → vault → paper/live.

## Archivos
| archivo | rol | ¿lo editas? |
|---|---|---|
| prepare.py | datos KuCoin, targets 1/4/8/12/24h, walk-forward purgado, métricas, backtest, DSR, gates | NO (fijo) |
| strategy.py | features + modelo + calibración | SÍ (lo único mutable) |
| loop.py | keep/revert, ledger results.tsv, modo auto, vault | NO |
| program.md | instrucciones para un agente (Claude Code) que corra el loop | tú |
| live.py | entrenamiento final + señales horarias + monitor/kill-switch (paper) | conectar execute() |
| synth.py | datos sintéticos para probar el pipeline offline | opcional |

## Flujo
```
python prepare.py download 730     # universo top-50 + velas H1 (2 años)
python loop.py baseline            # primera métrica
python loop.py auto 30             # mutación automática de hiperparámetros
python loop.py run "idea X"        # tras editar strategy.py a mano/agente
python loop.py final               # VAULT (una sola vez)
python live.py train && python live.py run
```
Dry-run offline: `python synth.py && python loop.py baseline`.
Variables: TRAIN_STRIDE (3 por defecto; sube para ir más rápido), COST_BPS, TIME_BUDGET, LOOP_METRIC=vol|dir|all.

## Qué mide
- Dirección (h=1,4,8,12,24): BSS vs tasa base, AUC, ECE, backtest L/S neto de costos, Deflated Sharpe.
- Volatilidad (h=4,8,12,24): skill vs HAR-RV (baseline fijo) y BSS del evento "expansión de vol" (vol futura > vol de la última semana).
- Métrica del loop por defecto: vol_skill_vs_HAR + BSS_expansión.
- Gates (deben pasar en el vault): vol gana a HAR, expansión BSS>0, ECE<0.03, dirección BSS>0, Sharpe neto>0 con DSR>0.95.

## Salvaguardas
- check_causal: recalcula features con el futuro truncado; si cambian => aborta.
- Embargo de 24h entre train y test; el vault (último 20%) no existe durante el loop.
- DSR penaliza por nº de trials del ledger.

## Advertencias
- Top-50 actual => sesgo de supervivencia. Market cap viene de CoinGecko, no de KuCoin.
- Shorts requieren futuros. Costos por defecto: 10 bps/lado.
- TimesFM-3: PARAMS["timesfm"]=True usa timesfm_features (NO probada; GPU; pesos con licencia no comercial).
- live.py es paper; execute() es el punto donde conectas tu cliente KuCoin. El kill-switch con pocas muestras es ruidoso.
- Probado solo con datos sintéticos (no pude llegar a KuCoin desde el sandbox).
