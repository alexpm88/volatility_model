# Progress & Historical Log — Registro de Récords y Aprendizajes

---

## 1. Cuadro de Honor — Campeones Actuales del Sistema

### A. Modelo Cripto H1 (`strategy.py`)
- **Campeón Vigente**: **Trial 38** (`KEEP`, `max_depth=5`)
- **Score**: **`0.26105`** (récord; +0.00478 sobre el Trial 21)
- **Métricas**:
  - `vol_skill`: **0.14558** (nuevo máximo, supera al benchmark HAR-RV en todos los horizontes)
  - `exp_bss`: **0.11546**
  - `dir_bss`: −0.02552 · `best_net_sharpe`: −0.132
- **Innovación Clave**: **capacidad extra** (`max_depth` 4→5) sobre la base de **descomposición de saltos HAR** (Bipower Variation + Signed Realized Semivariance) y Rough Volatility (Engine A). Evidencia: el frente de `vol_skill` responde a más capacidad del boosting, no a más features.

### B. Modelo Multi-Activo Diario (`multi/strategy_multi.py`)
- **Campeón Vigente**: **Trial 45** (`KEEP`, V5.1-M1: `vol_term_5_63` sobre la base SRT-corpus; `max_iter` 350 intacto, `calib=none` intacto)
- **Score**: **`0.10546`** (récord vigente; +0.00152 vs 0.10394 de Trial 42)
- **Métricas** (dev / holdout-20%):
  - `vol_skill`: **0.04237** / **0.09141**
  - `exp_bss`: **0.08108** / **0.08706**
  - `dir_bss`: −0.01799 · `best_net_sharpe`: +0.116 (dev) / +0.571 (holdout)
  - Ranking de Rendimiento: Oro (`GLD`, `GC=F`, `GDX`) líder; Cripto (`BTC-USD`) rentable a bajo Sharpe.
- **Innovación Clave**: V5.1-M1 — `F["vol_term_5_63"] = rv[5] - rv[63]` (vol-term-premium inversion 5d/63d); causal (check_causal OK), no redundante con `cyc_*`. + ratios de saltos `jump_ratio_21` / `signed_jump_21` + `max_iter` 200→350. Snapshot `multi/snapshots/strategy_multi_best.py` == `strategy_multi.py` (≡ live).
- **Veredicto V5.1-M1 (08-Oct)**: dev KEEP (+0.00152 vs 0.10394); vault **0.174636** > V4.4 0.17450 (nuevo high, gates 4/5). Lift vault marginal (+0.000136 < MIN_DELTA 0.0005) y casi entero en `exp_bss`; `vol_skill`/Sharpe holdout planos/levemente abajos. Shippable, no profundiza el core edge: el `LOOP_METRIC=vol` premia `exp_bss` a costa de `dir_bss`/`vol_skill`. Cuello de botella = métrica del loop, no features.

### C. Motor de Carteras de Renta Variable (`portfolio_engine/`) — NUEVO
- **Estado**: módulo completado y validado por primera vez (antes era un paquete a medias).
- **Backtest 2021-09-27 → 2026-09-25** (25 acciones, rebalanceo mensual, top-20, vol target 10%):
  - NAV 100,000 → **168,815** (+68.81%), **CAGR +11.09%**, vol anual 8.75%, **Sharpe +1.25**, MDD −11.25%, Calmar +0.99.
  - **Dividendos cobrados: 10,855** · costos totales 821 (5 bps/lado) · turnover diario 0.99%.
  - 48 rebalanceos ejecutados, 16 posiciones medias, 0 NaNs en el panel (caché sin huecos).
- **Validación formal** (`python3 -m portfolio_engine --validar`, `validation.py`): **GATES 4/4** — 5 folds secuenciales con Sharpe medio **+1.37** (peor +0.72), rejilla de 18 combinaciones con Sharpe medio +1.11 (peor +0.87), ningún fold con drawdown peor que −25%, y supera el percentil 90 del placebo. El fold 4 (2024-12→2025-10) es el peor: Sharpe +0.72 con el MDD máximo (−11.25%).
- **Caveat de honestidad**: el placebo de **selección aleatoria** de 20 de 25 blue chips produce Sharpe medio **+1.02** (p90 +1.09, máx +1.10). Por tanto el grueso del rendimiento es **beta alcista del período**, no habilidad: el *skill de selección* multifactorial medido contra el placebo es de ≈ **+0.23 de Sharpe**. Sus métricas **no son comparables** con el Cuadro de Honor cripto/multi (que usa portafolios dollar-neutral L/S sobre retornos netos de costos).

---

## 2. Resumen de Ledgers de Evaluación

### Evolución Reciente Cripto (`results.tsv`)
| Trial | Score | Vol Skill | Exp BSS | Dir BSS | Net Sharpe | Estado | Descripción del Experimento |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 15 | 0.25390 | 0.13855 | 0.11535 | -0.01731 | +0.437 | **KEEP** | Features estructurales: pos30, breakout168, lead BTC |
| 16 | 0.25390 | 0.13855 | 0.11535 | -0.03059 | -1.535 | DISCARD | KMeans3 por régimen en fit |
| 17 | 0.25355 | 0.13894 | 0.11461 | -0.01701 | +0.028 | DISCARD | Cadenas de Markov rodantes de signo |
| 18 | 0.25390 | 0.13855 | 0.11535 | -0.00252 | +1.217 | DISCARD | Calibración Platt aislada |
| 19 | 0.00000 | 0.00000 | 0.00000 | 0.00000 | 0.000 | CRASH | Roughness sin lag (detectado por `check_causal`) |
| 20 | 0.25544 | 0.14018 | 0.11526 | -0.01925 | +0.458 | **KEEP** | Rough Volatility Engine A (Hurst causal con lag 1d) |
| 21 | **0.25627** | **0.14043** | **0.11584** | -0.01903 | -0.200 | **KEEP** | **Descomposición de saltos HAR: Bipower + Signed Jumps** |
| 22 | 0.25604 | 0.14185 | 0.11419 | -0.01774 | +0.294 | DISCARD | Tail risk: VaR Cornish-Fisher + tail_fatness (revertido limpiamente) |
| 23 | 0.24483 | 0.13435 | 0.11048 | -0.02426 | -0.188 | DISCARD | Spillover BTC→altcoins: 9 features de lead-lag / ratio / correlación rodante 168h (dilución de features; revertido limpiamente) |
| 24 | 0.25625 | 0.14053 | 0.11572 | -0.01989 | -0.901 | DISCARD | Spillover-lite: sólo `corr_btc_168` + `altbtc_lrv_ratio` (empate técnico: −0.00002 vs récord ⇒ sin información incremental; revertido limpiamente) |
| 38 | **0.26105** | **0.14558** | 0.11546 | -0.02552 | -0.132 | **KEEP** | **C2.1 `max_depth=5`: NUEVO RÉCORD (+0.00478) — el frente de vol responde a más capacidad** |
| 39 | 0.25831 | 0.14503 | 0.11328 | -0.03133 | **+0.658** | DISCARD | C2.2 `max_depth=6`: eje de capacidad saturado (4→5 ▲ / 5→6 ▼); mejor Sharpe neto cripto hasta la fecha |
| 40 | 0.25889 | 0.14504 | 0.11386 | -0.03660 | +0.063 | DISCARD | C2.3 `max_iter=250` sobre base depth=5: 150 sigue siendo suficiente (eje de iteraciones saturado; 804s) |
| 41 | 0.26049 | 0.14593 | 0.11456 | -0.02660 | -0.541 | DISCARD | **V5.0**: features de régimen local 168h (`reg_z_168`, `reg_persist_168`, causal/expanding-local, check_causal OK). Dev score < champion 0.26105 (−0.00056, por debajo de MIN_DELTA 0.0005 ⇒ revertido). `vol_skill` ≈ idéntico (+0.0003), `best_net_sharpe` −0.541 (backtest gate sigue ❌). **Lección V5.0**: el leak dev/vault (folds expanding incluyen post-2022 en train) invalida cualquier feature de ventana-corta para salvar `vol_skill` en el holdout 2022-2025; cripto → research-only. `strategy.py` idéntico al snapshot (verificado `diff`).
| 42 | 0.26107 | 0.14553 | 0.11554 | -0.02595 | -0.334 | DISCARD | **V5.1**: `vol_term_6_168 = rv[6] - rv[168]` (log-ratio término vol corto/largo, causal, check_causal OK). score +0.00002 vs champion (< MIN_DELTA 0.0005 ⇒ revertido). `vol_skill` 0.14553 ≈ 0.14558 (sin mejora); `best_net_sharpe` −0.334 (backtest sigue ❌). **Confirma V5.0**: 2 probes de fase V5.x no mueven `vol_skill`/Sharpe del holdout; el colapso 2022-2025 es estructural (sizing en arnés `prepare.py`, fuera de rieles) + leak dev/vault. **V5.x CERRADA**; cripto research-only; `strategy.py` ≡ snapshot campeón.

> **Aviso de integridad**: los Trials **9, 11, 12, 26 y 27** figuran como `discard` pero **nunca fueron realmente evaluados**: un bytecode obsoleto (`__pycache__`) hizo que el harness evaluara la estrategia anterior (score idéntico al best). Están anotados en `results.tsv` y el bug está corregido en `loop.py` (ver lección 8 de la §3).

### Barrido de hiperparámetros ya validado (Trials 28-37, con el fix del pyc)
| trial | mutación | score | vol_skill | exp_bss | dir_bss | netSharpe | veredicto |
|:---:|---|---|---|---|---|---|---|
| **21** | **base (récord)** | **0.25627** | 0.14043 | 0.11584 | −0.01903 | −0.200 | **KEEP** |
| 28 / 36 | `lr=0.03` | 0.23934 | 0.12795 | 0.11139 | −0.01223 | −0.080 | DISCARD (reproducible ×2) |
| 29 | `max_iter=400` | 0.25556 | **0.14277** | 0.11279 | −0.03944 | **+0.438** | DISCARD (−0.00071) |
| 30/32/33/35/37 | `calib=platt` | 0.24484 | 0.14043 | 0.10441 | **−0.00283** | +0.266 | DISCARD (reproducible ×5) |
| 31 | `min_leaf=400` | 0.25548 | 0.14016 | 0.11532 | −0.01960 | +0.063 | DISCARD (−0.00079) |
| 34 | `lr=0.02` | 0.21129 | 0.10543 | 0.10586 | −0.00833 | −0.550 | DISCARD (reproducible ×2) |

**Cobertura del espacio**: probado `lr∈{0.02,0.03,0.05}`, `max_iter∈{150,400}`, `min_leaf∈{200,400}`, `calib∈{none,platt}` (y `l2=20` / `max_iter=400` con el set de features antiguo). **Sin probar**: `max_iter∈{80,250}`, `max_depth∈{3,5,6}`, `min_leaf∈{100,800}`, `l2∈{0,5}`. Conclusión: el `PARAMS` vigente es un **óptimo local de una coordenada** (los dos rivales más cercanos quedan a ~0.0007-0.0008 del umbral requerido de +0.0005).

**Dos hallazgos accionables del barrido**:
1. **`calib=platt` arregla la dirección y el backtest, pero el score lo descarta siempre**: `dir_bss` pasa de −0.01903 a **−0.00283** y el net Sharpe de −0.200 a **+0.266** (reproducible en 5 ejecuciones idénticas), a costa de `exp_bss` (0.11584→0.10441). Es la evidencia más limpia de que la métrica `LOOP_METRIC=vol` **bloquea sistemáticamente** la mejora de los gates de dirección/backtest (ver lección 6 y TODO Fase 4).
2. **`max_iter=400` logra el mejor `vol_skill` (0.14277) y el mejor net Sharpe (+0.438) jamás medidos**, pero pierde `exp_bss`; queda a 0.00071 del récord ⇒ la frontera vol↔expansión está prácticamente agotada con este feature set.


### Evolución Reciente Multi-Activo (`multi/results.tsv`)
| Trial | Score | Vol Skill | Exp BSS | Dir BSS | Net Sharpe | Estado | Descripción del Experimento |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 22 | 0.07099 | 0.01336 | 0.06937 | -0.01174 | +0.183 | DISCARD | Hiperparámetro `max_depth=2` |
| 23 | 0.07005 | 0.01297 | 0.06834 | -0.01126 | +0.304 | DISCARD | Interacciones de régimen x flujo |
| 24 | 0.06088 | 0.00989 | 0.06468 | -0.01369 | +0.053 | DISCARD | Momentos superiores skew/kurt |
| 25 | 0.07142 | 0.01295 | 0.06840 | -0.00994 | +0.137 | DISCARD | Momentum ajustado por volatilidad |
| 26 | 0.06111 | 0.00649 | 0.06605 | -0.01143 | +0.287 | DISCARD | Roughness directa (sube Sharpe pero baja score compuesto) |
| 27 | 0.06269 | 0.00790 | 0.06672 | -0.01193 | +0.222 | DISCARD | Roughness normalizada (z-score + rank) |
| 29 | **0.08003** | **0.02158** | **0.06958** | -0.01113 | +0.122 | **KEEP** | **NATR14 + True Range Ratio (Récord Multi-Activo)** |
| 30 | 0.07931 | **0.02431** | 0.06913 | -0.01413 | **+0.277** | DISCARD | Macro `GLD/SPY` (4 features): **récord de `vol_skill`** y de Sharpe neto, pero pierde `dir_bss` ⇒ −0.00072 (revertido limpio) |
| 32 | 0.07975 | 0.02158 | 0.06941 | -0.01124 | +0.054 | DISCARD | M3.3 deadband=0.02 en dir via estrategia (sin tocar arnes): -0.00028 vs record; el turnover pesa poco en el score all; frente cerrado |
| 32 | 0.07975 | 0.02158 | 0.06941 | -0.01124 | +0.054 | DISCARD | M3.3 deadband=0.02 en dir via estrategia (sin tocar arnes; CONF_MIN del arnes intacto): -0.00028 vs record; vol_skill intacto, exp -0.00017, dir +0.00011; el turnover pesa poco en el score all; frente cerrado |
| 31 | 0.07516 | 0.02209 | 0.06555 | -0.01248 | +0.197 | DISCARD | Macro-lite (2 features de régimen/vol): **peor** que la familia completa ⇒ los momentos del ratio también aportan (frente macro cerrado) |
| 33 | **0.09989** | **0.03877** | **0.07187** | -0.01075 | +0.201 | **KEEP** | **NUEVO RÉCORD MULTI: bloque SRT-corpus (GARCH(1,1)+Kalman OU+Volume Profile+VWAP+SuperTrend, 22 feas)**: +0.01986 vs 0.08003; `vol_skill` **0.03877** (+0.017, récord) y `exp_bss` +0.002; `dir_bss` h1 **+0.00141** (primer BSS direccional positivo); gates vol+exp OK; snapshot 72 features; detalle `docs/srt-corpus-rules.md` |
| 34 | 0.10019 | 0.03868 | 0.07200 | -0.01048 | +0.142 | DISCARD | M3.6 calendario duro (`is_mon/is_fri/is_mstart/is_mend/mend_dist`, 5 feas): +0.00030 vs récord **pero < `MIN_DELTA` 0.0005** ⇒ anti-ruido lo descarta; calendario NO aporta señal incremental sobre el cíclico; revert limpio |
| 42 | **0.10394** | **0.04280** | **0.07904** | -0.01791 | +0.153 | **KEEP** | **M3.4 `auto 10` (pyc fix): NUEVO RÉCORD MULTI — único KEEP de 10 trials válidos.** Mutación `max_iter: 200→350`; +0.00405 vs 0.09989. 9 DISCARD (Trial 40 `max_iter=100` catastrófico `0.01137`; `min_leaf/l2/max_depth/lr/shrink` saturados o degenerados sobre base 72-feas). `calib=none` intacto. Live == snapshot (diff sólo `max_iter`). 

| 28 | **0.07305** | **0.01426** | **0.07000** | -0.01121 | +0.116 | **KEEP** | **Descomposición de saltos HAR: Bipower + Signed Jumps** |

> **Integridad (multi)**: los Trials **3 (`l2=0.0`), 4 (`max_depth=2`) y 10 (`max_iter=350`)** figuran como `discard` pero **nunca fueron evaluados** (mismo bug de bytecode obsoleto; score idéntico al best). Anotados en `multi/results.tsv` y corregido con el mismo fix `_purge_stale_pyc()` en `multi/loop_multi.py`.
>
> **Asimetría de métrica entre arneses**: el **cripto** usa `LOOP_METRIC=vol` ⇒ score = `vol_skill + exp_bss` (ciego a dirección y backtest); el **multi** usa `LOOP_METRIC=all` ⇒ score = `vol_skill + exp_bss + dir_bss`. Por eso en multi sí se pueden retener mejoras de dirección y en cripto no (ver lección 6).

---

## 3. Principales Lecciones Aprendidas de la Batería Cuantitativa

1. **La causalidad no es negociable**: Un modelo que no respeta el flujo de tiempo genera métricas ilusorias en el laboratorio y quiebra en vivo. `check_causal` es el filtro de supervivencia más valioso del repositorio.
2. **Los saltos y la difusión continua se comportan de forma distinta**: Mezclar saltos de liquidez con la volatilidad browniana ordinaria confunde al regresor. Al descomponerlos con Bipower Variation, el modelo aprende por separado la inercia continua de la fragilidad extrema.
3. **El mercado de metales (Oro) es el más predecible para el modelo**: En las pruebas multi-activo, `GC=F` y `GLD` obtienen los mayores ratios de Sharpe neto (+0.69 / +0.80), superando al S&P 500 y mitigando el ruido durante crisis sistémicas.
4. **Dollar-neutralidad estricta para controles placebo**: Si un test placebo no está centrado en $\sum w_i = 0$, la tendencia alcista natural del mercado contamina el control y falsea el Sharpe nulo.
5. **La información de BTC ya estaba capturada — frente CERRADO (Trials 23 y 24)**: la familia completa de 9 features de spillover degradó ambos componentes (`vol_skill` 0.14043→0.13435 y `exp_bss` 0.11584→0.11048, score 0.24483), mientras que la variante *lite* de 2 features (`corr_btc_168` + `altbtc_lrv_ratio`) empató técnicamente el récord (0.25625, −0.00002; `vol_skill` incluso 0.14053). **Evidencia monotónica**: a menos features de la familia, más cerca del récord (9→0.24483, 2→0.25625, 0→0.25627). Conclusión: el co-movimiento y el desacople alt/btc **no aportan información incremental** sobre los canales directos ya presentes desde el Trial 15 (`btc_ret_1`, `btc_lrv_6`, `btc_lrv_24`); el daño del Trial 23 era pura dilución de ruido correlacionado. No reabrir este frente.
6. **El loop es ciego a la dirección (hallazgo estructural)**: `LOOP_METRIC=vol` puntúa sólo `vol_skill + exp_bss`, así que ninguna mejora de `dir_bss` o de Sharpe puede retenerse: el Trial 18 llevó `dir_bss` de −0.01731 a −0.00252 y el net Sharpe de −0.250 a **+1.217**, y aun así fue `DISCARD` por score idéntico. Esto explica por qué los gates `direccion_BSS>0` y `backtest_neto_Sharpe>0_y_DSR>0.95` llevan 24 trials sin aprobarse: el objetivo no los mide. Ver TODO Fase 4.
7. **Más features no es mejor**: entre Trials 15→23, cada mutación que añadió *familias nuevas de información real* (roughness, saltos HAR, NATR) subió el score; cada mutación que añadió *derivaciones de información ya presente* (spillover) lo bajó o lo dejó igual. El criterio de utilidad debe ser la novedad informativa, no el número de columnas.
8. **BUG DE INTEGRIDAD DEL LEDGER: bytecode cacheado (detectado y corregido el 26-Sep)**: `loop.py auto` muta `PARAMS` con `re.sub`; si el valor nuevo tiene **el mismo nº de caracteres** (`'0.05'→'0.02'`, `'4'→'3'`) y la escritura cae **en el mismo segundo** que la importación previa de `strategy.py`, CPython acepta `__pycache__/strategy.cpython-*.pyc` como válido (valida por `mtime` en segundos + tamaño) y `prepare.py` **evalúa el código ANTERIOR**. Efecto: la fila del ledger registra un `discard` con score **idéntico al best** sin haber evaluado el mutante ⇒ falso negativo silencioso. Filas afectadas y anotadas: **9, 11, 12, 26, 27**. Prueba forense: el `.pyc` fue escrito 3 ms **antes** que `strategy.py` (mismo `mtime_int` y `size`) mientras el bytecode no coincidía con el fuente (`marshal.dumps(pyc) != marshal.dumps(compile(fuente))`). **Fix aplicado**: `loop.py` purga `__pycache__/strategy.*.pyc` en `evaluate_once()` (y al inicio de `auto()`) + usar siempre `PYTHONDONTWRITEBYTECODE=1 python3 -u`. Lección general: **nunca confiar en un resultado de búsqueda cuyo score sea exactamente igual al mejor previo**.
9. **V4.1 resuelve el dilema métrica-vs-gates con doble ledger (28-Sep)**: separar `results.tsv` (`vol`) de `results_all.tsv` (`all`) permite retener AMBAS configs óptimas sin mezclar definiciones de score: la base `max_depth=5`+`calib=none` gana en `vol` (`0.26105`) y la misma base + `calib=platt` gana en `all` (`0.24720`, con `vol_skill` 0.14558 intacto, `dir_bss` −0.00319 y net Sharpe h24 +1.18). Lección: cuando el objetivo oficial y los gates discrepan, **no se elige uno — se optimizan los dos en ledgers separados**.
10. **V4.2: el fallo operativo también se fija en infra, no en memoria (02-Oct)**: el lanzador `run_trial.sh` convierte las dos lecciones operativas (pyc obsoleto, logs bufferizados) en guardas ejecutables (rc=3 anti-paralelo, rc=4 base-limpia, env fijado, monitor en /tmp). Regla: **todo trial manual pasa por `./run_trial.sh`**; `auto N` directo sólo con el env de la cabecera.
11. **Feature causal ≠ recursión inocua: la semilla importa (04-Oct, SRT-corpus)**: la recursión GARCH(1,1) era estrictamente causal *en el interior*, pero la semilla `v0 = media incondicional de TODA la serie` miraba al futuro; `check_causal` lo detectó (`garch_gap` LEAK) aunque el resto del bloque pasara. Fix: semilla = media de los **primeros 63 retornos** + warmup de 63 barras en `NaN`, de modo que P y Pc comparten inicio y el estado recursivo coincide pasado el warmup → **5/5 bloques CAUSAL**. Lección: en recursiones forward, **toda condición inicial debe derivarse sólo del tramo visible**; el test de truncado no perdona ni la constante de arranque. Resultado: Trial 33 → **nuevo récord multi `0.09989`** con 22 features nuevas, confirmando que *familias informativas nuevas* sí suben el score (lección 7) — a diferencia de spillover/macro.
12. **El calendario duro NO supera el umbral anti-ruido (04-Oct, Trial 34)**: `is_mon/is_fri/is_mstart/is_mend/mend_dist` (5 flags/derivados puros de timestamp) sumaron **+0.00030** sobre el récord (0.10019 vs 0.09989) — dirección correcta pero **< `MIN_DELTA` 0.0005** ⇒ DISCARD. Los efectos lunes/viernes y fin-de-mes **ya estaban capturados** por los encodings cíclicos (`dw_sin/cos`, `m_sin/cos`, `mo_sin/cos`); añadir dummies duros de la misma información de calendario es *derivación de información ya presente* (lección 7), no novedad. También fija el límite de datos: el volumen por **sesión NY (apertura/cierre) vs otras sesiones no es derivable del panel diario** (un único volumen/día, hora=0) — requiere re-descarga H1 con costes de re-tuneo; documentado en `docs/srt-corpus-rules.md` §3.
13. **`auto 10` multi confirma saturación del feature-set sobre la base SRT-corpus (06-Oct, Trial 42)**: de 10 trials válidos con el pyc fix, **1 KEEP NUEVO RÉCORD `0.10394`** — únicamente en `max_iter` (200→350); el resto de hiperdimensiones (`min_leaf∈{50,100,250}`, `l2∈{0,5}`, `max_depth∈{2,3,4}`, `lr∈{0.02,0.08}`, `shrink∈{0.5,0.75,1.0}`) ni degeneran ni superan el récord. El `vol_skill` sube 0.03877→0.04280 (+0.004) pero `dir_bss` empeora −0.01075→−0.01791 y `exp_bss` +0.07187→+0.07904: la mejora del score es **casi entera de `exp_bss`**, con `dir_bss` negativo → la métrica `LOOP_METRIC=vol` premia la expansión a costa de dirección. El único Trial 40 `max_iter=100` `0.01137` muestra una **faja de inestabilidad**: iteraciones insuficientes colapsan el boosting. Lección: sobre una base de features informativa (SRT-corpus), la capacidad restante reside en `max_iter`, no en más features; pero el cuello de botella sistémico sigue siendo la métrica del loop.

14. **V4.3 Stress tests (06-Oct, snapshot multi `0.10394`, `LOOP_METRIC=vol`, `calib=none` intacto)**: GFC-2008 / COVID-2020 / deuda soberana / shocks de tasas 2022, cada crisis como entrenamiento pre-crisis + embargo → test OOS (única partición causal: ventanas < `MIN_TRAIN_DAYS`). Baseline vault OOS score 0.12023 (dir_bss −0.0017 / exp_bss +0.0871 / vol_skill +0.033 / net Sharpe +0.026). Crisis: GFC dir_bss +0.029 / exp_bss +0.372 / Sharpe +3.11; COVID dir_bss +0.076 / Sharpe +2.00 (exp_bss NaN, 311 filas); Deuda-soberana dir_bss −0.019 / Sharpe +1.27; Shocks-tasas-22 dir_bss +0.034 / exp_bss +0.066 / vol_skill +0.0225 / Sharpe +0.73. **Gate-5 PASS**: el core predictivo (dirección > baseline en 3/4 crisis, expansión BSS elevada y estable, Sharpe OOS +0.73–3.11) no colapsa. El gate `vol_skill` VS HAR se rompe en GFC (−3.22) — el **mismo tipo de fallo que ya ocurre en baseline** (`calib_ECE`/`placebo`/`DSR` ya falsos sin crisis) y se documenta como la limitación estructural de `LOOP_METRIC=vol` (Lesson 6/9 doble ledger): como score único premia `exp_bss` a costa de `dir_bss`/`vol_skill`, y los gates de dirección/backtest sólo aprobables en `all`. Veredicto: modelo multi robusto a crisis → procede V4.4 Vault sellado.

15. **V4.4 Vault (06-Oct): multi sellado, cripto bloqueado por holdout** (`loop.py final` NO ejecutado — el guardia `vault_runs.log`/data-snooping prohíbe sellar un modelo no replicado): el campeón multi (Trial 42 `0.10394`) **replica y supera** el dev en el 20% final — vault score **0.17450**, vol_skill +0.0926 > HAR, exp_bss +0.0854, dir_bss −0.00355, net Sharpe +0.7525, gates 4/5 sin fallos nuevos → **multi SELLADO** (marcador `multi/vault_runs.log`). El campeón cripto (Trial 38 `calib=none`, dev 0.26105) **colapsa** en el holdout 20%: vol_skill +0.1456→−0.0784 (VS HAR), net Sharpe +0.153→−2.68 → **cripto BLOQUEADO**: el Vault cumple su función de árbitro. Candidato `calib=platt` (all-ledger 0.24720, dev Sharpe +1.18, 3 gates) es el siguiente retry; si no replica, el cripto H1 se restringe a research-only. Lección: el doble-ledger (Lesson 9) no elimina el dev→holdout gap — el campeón `vol`-ledger sobre-ajusta `vol_skill` a dev y colapsa OOS; el holdout 20% es el árbitro final indiscutible.

16. **V4.4 Vault retry (06-Oct): cripto `calib=platt` también colapsa** — el Vault es el árbitro final: el campeón `vol`-ledger (calib=none, 0.26105 dev) FALLA holdout (vol_skill −0.0784, net Sharpe −2.68); el retry `calib=platt` (all-ledger 0.24720) FALLA holdout (vol_skill −0.0784 idéntico → platt no salva el R2 OOS; ECE gate OK, pero vol/dir/backtest ❌, score 0.0725). `exp_bss` (+0.15) es la única señal que sobrevive en ambas calibraciones → **cripto H1 a research-only / no se sella** (`loop.py final` NO ejecutado, guardia data-snooping). El **MULTI es el único producto shippable**: vault 0.17450 replica+excede dev 0.10394, gates 4/5 sin fallos nuevos, sello en `multi/vault_runs.log`. Lección: frente a regime shift 2022-2025, el modelo H1 de volátil sobre-ajusta; necesita V5.x (features de régimen OOS / vol-targeting). `strategy.py` restaurado al campeón calib=none (== snapshot).


---

## 17. P5.6–P5.7 Breadth Sweep + Ship Decision (11-Oct 2026)
- **P5.6 (40-syms breadth; 429 cleared; 102 bt = 3 configs × 34 folds)**: sweep top_k {20,25,40} @40syms @5bps. **`top_key=20@40` (selección REAL, elige 20/40) = 1.0615 < baseline 1.2472 ⇒ ❌ selección cross-sectional NETO NEGATIVA a escala** (3/4 gates FALLA). `top_key=25@40`=1.1777 INVALIDA el ADOPT de P5.5 (1.3104@25 era degeneria 25=full-universe; Δ−0.133). **`top_key=40@40` (full-breadth) = 1.3435/4/4 (mejor), folds_min +0.935 (el mejor), monótono en width** ⇒ gana por DIVERSIFICACIÓN, no por skill de ranking. Artefactos: reports/p56_topk/{summary,decision}.json.
- **Veredicto ship (confirmado 11-Oct)**: **(b) V5.1+B2 `top_key=20` INTACTO** (1.2472/4/4, 4/4 gates, floor conservador) como default productivo. `top_key=40` full-breadth = **opt-in P5.7b** (kwarg validado; NO adopt como default). Alpha del modelo = volatility SIGNAL (Engine A rough vol/HAR jumps), NO del ranking.
- **P5.7 [COMPLETADO — 11-Oct]**: `top_key=None` full-breadth (Design B). backtester.py L29 `__init__` default `top_key=20`→`None` (None-safe) + None-guard en `_target_weights`; rank_and_select_top_k (signals.py L85) None-safe (`top_key is None => all valid dropna-filtered`) — **NO muta el baseline top_key=20** (1.2472/4/4). `top_key=None@40syms = 1.3435/4/4` (≡ top_key=40@40 P5.6; full-breadth; folds_min +0.935), gates 4/4. RE-RE-VALIDADO: el primer intento con `list(self.symbols)` guard fue DIVERGENTE (1.0298/3/4, bypassa el dropna L84) → revertido a llamada directa a rank_and_select_top_k (H9: signals.py L85 None-safe + backtester.py L100 revert). CLI `__main__.py` L33 pasa `top_key` explícito (default 20 en capa CLI → `__init__` default `None` es DEAD PATH en shipped paths) ⇒ safe, no int(None) risk. Artefactos: reports/p57_none/{summary,decision}.json; commits H7-H9 (cf4b70d P5.7a / d900bf1 P5.7b / 9063a58 reports). Full-breadth `top_key=None` = opt-in P5.7b (kwarg validado); default productivo **V5.1+B2 `top_key=20` INTACTO** (1.2472/4/4).
- **Repo**: `git init` + push a github.com/alexpm88/volatility_model (master=c12fa5b, 4 commits, 101 files); reports/p56_topk corregido (ADOPT→opt-in + caveat reproducibility); `/tmp/cline/recover_backtrader.sh` = one-command rescue tras restaurar el drive.
- **P5.8 [COMPLETADO — 11-Oct]**: Holdout 3-fold OOS full-breadth (`top_k=None@40syms`) usando 10y datos (2514 dias, 2016-2026). Walk-forward 3-fold (train=630, OOS=628). **In-sample 10y Sharpe 0.8977** (vs P5.6/P5.7 5y Sharpe 1.3435 — inflado por bull market). Placebo p90 (top_k=20 aleatorio) = 1.0661 > 0.8977. OOS folds: Fold 1 (2019-2021, COVID) Sharpe 0.7124 MDD -26.14%; Fold 2 (2021-2024) Sharpe 0.9554 MDD -11.24%; Fold 3 (2024-2026) Sharpe 1.3532 MDD -12.72%. OOS avg 1.0070 (min 0.7124). **Gates 2/5**: ✅ Sharpe promedio positivo, ✅ todos Sharpe > 0; ❌ MDD -25% (Fold 1 COVID), ❌ OOS no supera placebo p90 en ningún fold, ❌ min OOS < 90% del in-sample 5y (1.3435). **Decisión: SUSPECT_OVERFIT** (overfit a bull market 2021-2026). Full-breadth no supera el placebo → alpha = volatility SIGNAL (inverse-vol + vol targeting), no de ranking/breadth. **V5.1+B2 `top_key=20` INTACTO** (1.2472/4/4); full-breadth = opt-in P5.7b, NO default. Artefactos: `reports/p58_holdout/{summary,decision}.json`; `portfolio_engine/p58_holdout.py` (runtime harness); cache `universe_40_10y.pkl`.

---

## 18. P5.9 Volume-Price Accumulation/Distribution Regime Features (11-Oct 2026)

- **Objetivo**: Detectar regimes de acumulación/distribución basados en dinámica volumen-precio; integrar scoring per-asset en el ranking y trigger de régimen en el backtester.
- **Features nuevas en `signals.py`** (`compute_asset_features`):
  - `lv`: $\ln(V_t / V_{t-1})$ (causal, shift(1)).
  - `volume_zscore_21`: z-score de 21d; detecta spikes (>1.5σ) o dried-up (<<0).
  - `vol_price_corr_21`: correlación 21d (min 14) retornos↔cambios volumen; +: tendencia confirmada; -: divergencia.
  - `acc_dist_score`: $\text{sign}(r_t) \cdot \text{sign}(lv_t) \cdot |r_t| \cdot \max(0, z_{V,21})$.
- **Composite Score** (`rank_and_select_top_k`): peso 0.10 en acc_dist_score; pesos anteriores escalados 10% proporcionalmente (0.315/0.270/0.180/0.135).
- **Trigger `acc_dist`** (`backtester.py` `_in_bear_regime`): Distribution = price < MA(regime_window) + volume > avg + k*std → cash. Accumulation = price ≥ MA + volume > avg + k*std → stay invested. Proxy cross-sectional median (o `regime_series`/`regime_volume_series`).
- **Bug fix**: `validation.py` `run_sensitivity` filtra `top_k`/`target_vol`/`rebalance_freq` de `**kw` antes de forward a `PortfolioBacktester` (evita `TypeError: multiple values for keyword argument`).
- **Smoke tests** (25 syms, 5y cache):
  - acc_dist regime (k=1.0): Sharpe **1.0277**, CAGR 9.44%, MDD -11.11%, 46 rebalanceos, avg 8.0 pos.
  - Baseline (regime_filter=False): Sharpe **1.0595** (backward compatible).
  - run_sensitivity: bug fix confirmado, 1 resultado retornado sin error.
