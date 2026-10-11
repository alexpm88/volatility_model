# SYSTEM.md — Sistema de Volatilidad Cuantitativo Multi-Activo

> Estado: OPERATIVO con datos reales. Dos harnesses fijos + un loop de evolución cada uno.
> Regla de oro: NUNCA editar `prepare.py` / `multi/prepare_multi.py` durante la evolución
> (salvo bug de corrección, documentado en results.tsv ANTES del vault).
> Solo se muta `strategy.py` (crypto H1) y `multi/strategy_multi.py` (multi-activo diario).

## 1. Arquitectura

```
                    ┌────────────────────────────────────────────┐
   CRYPTO H1        │  prepare.py (HARNESS FIJO)                 │   loop.py
   KuCoin 50 syms   │  targets dir/vol/exp · walk-forward purgado│   keep/revert + ledger
 ──────────────────>│  embargo 24h · vault 20% · DSR · gates     │<── python loop.py run "x"
   strategy.py      │  costos 10bps/lado · placebo interno       │   python loop.py auto 20
   (ÚNICO mutable)  └────────────────────────────────────────────┘
                    ┌────────────────────────────────────────────┐
   MULTI DIARIO     │  multi/prepare_multi.py (HARNESS FIJO)     │   multi/loop_multi.py
   SPY QQQ GDX GLD  │  igual contrato + costos POR CLASE         │   idéntico keep/revert
   GC=F SI=F SLV    │  + test PLACEBO (permuta señales)          │<── python multi/loop_multi.py run
   BTC-USD          │  + comparativa rentabilidad activo/clase   │
 ──────────────────>│  76 folds × 10 tareas (dir/vol/exp)        │
   strategy_multi   └────────────────────────────────────────────┘
```

Ambos harnesses comparten núcleo de métricas (`prepare.py`): Brier/BSS, AUC, ECE,
Deflated Sharpe, `LeakageError`.

## 2. Contrato de estrategia (lo único que el loop muta)

```python
# strategy.py (crypto, panel índice (sym, ts) H1):
def build_features(panel) -> DataFrame   # MISMO índice; SOLO info <= t
def fit(Xtr, ytr, task, h) -> objeto con .predict(X)
# task: "dir" (P(ret>0)), "vol" (log RV futura), "exp" (P(vol>vol_63d))

# strategy_multi.py (diario): mismo contrato; targets en días 1/5/10/21.
```

`check_causal()` reevalúa `build_features` con el futuro truncado: si alguna feature
cambia, el harness ABORTA con `LeakageError`. Nunca desactivar.

## 3. Comandos (uso diario)

```bash
# CRYPTO (H1, 2 años, 50 símbolos KuCoin)
python prepare.py download 730      # refrescar datos (una vez)
python loop.py baseline             # primera corrida -> results.tsv
python loop.py run "descripción"    # 1 mutación: keep si sube el score, si no revert
python loop.py auto 20              # 20 mutaciones automáticas de PARAMS
python loop.py final                # VAULT (una sola vez en el proyecto)

# MULTI (diario, 33 años de SPY + oro/plata/BTC)
python multi/download_multi.py      # Yahoo (una vez)
python multi/prepare_multi.py dev   # eval directa (sin loop)
python multi/loop_multi.py baseline
python multi/loop_multi.py run "x"
python multi/loop_multi.py auto 10
```

## 4. Métricas y gates (lo que define "éxito")

- vol_skill: 1 − MSE_modelo/MSE_HAR-RV (OLS HAR por fold). Gate: >0 en >=3/4 horizontes (crypto), >=2/3 (multi).
- exp_bss: Brier skill de expansión de vol vs base rate. Gate: >0 en >=3/4 (crypto), >=2/3 (multi).
- dir_bss: Brier skill direccional vs base. Gate: >0 en >=3/5 (crypto), >=2/4 (multi).
- ece: error de calibración. Gate: <0.03 en todas las tareas.
- net_sharpe: L/S neto de costos reales por mercado. Gate: >0 con DSR>0.95 en algún horizonte.
- dsr: Deflated Sharpe (ajusta por número de pruebas).
- placebo (multi): permuta señales por fecha -> Sharpe debe ser ~0 y < real.

score (el número que el loop maximiza) depende de `LOOP_METRIC` en prepare*.py:
`vol` -> vol_skill+exp_bss · `dir` -> dir_bss · `all` -> vol_skill+exp_bss+dir_bss.
**Ejecución real (verificado 23-09 04:20)**: multi usa `all` por defecto
(prepare_multi.py:36); crypto usa `vol` por defecto (prepare.py:30) y `loop.py` NO fija
la variable -> en crypto keep/revert es CIEGO a dir_bss. Intención documentada = `all`
(ver §9); corregir en loop.py + re-baseline (decisión pendiente, ver §9).
El backtest L/S exige AMBOS lados (long y short) no vacíos; si no, día plano
(guard de neutralidad anti-drift, añadido tras detectar placebo inflado en h=10/21).

## 5. Estado actual (23 Sep 2026, tras 41 trials reales)

### CRYPTO (best trial 15, score 0.25390)
- vol_skill **+0.139** (bate HAR-RV 3/4 horizontes) · exp_bss **+0.115** · ECE OK
- netSharpe dev **+0.44** (h=1) tras mutación estructural pos30/breakout168/rank72/btc_lead
- trials 13 y 15 = KEEP (features de régimen y estructura); resto DISCARD auto-revertido
- trial 16 (regime-fit KMeans en `fit`): DISCARD — ver §9.3 (testado y rechazado)

### MULTI (best trial 14, score 0.07099)
- vol_skill +0.013 · exp_bss +0.069 · netSharpe +0.63 (h=21, DSR 0.995)
- Placebo 8 semillas: Sharpe permutado −0.14..+0.02 (≈0, gate anti-autoengaño OK)
- Ranking de rentabilidad (dev): crypto +0.92 > oro futuros +0.80 > GLD +0.65 > SPY +0.63 > plata
- mutaciones struct (24) y struct-lite (25) no superaron el margen: revertidas

### Vault
- NO gastado en ningún sistema (correcto: una sola prueba final cuando se detenga la evolución).

## 6. Roadmap de evolución (loop Karpathy)

Estado: pasos 1, 3 y 4 ya ejecutados en gran parte (features implementadas + baterías PARAMS).
Lo que falta es el paso bloqueante: **la dirección (dir_bss) es ≤0 en ambos harnesses**, así que
el backtest L/S no paga costos y el placebo del multi es rentable (autoengaño). El vault NO
debe gastarse hasta que dir_bss>0 y el placebo deje de ser rentable.

1. [crypto] features H1: hora del día (sin/cos), distancia a VWAP 24h, Garman-Klass,
   saltos (gap open), volumen firmado -> HECHO parcialmente (svol/flow_imb/cyc_*/vmin/vmax).
2. [crypto] dir con régimen: momentum x ciclo de vol (features explícitas:
   cyc_24_168, distancia a máx vol 30d) -> HECHO (trial 13 KEEP 0.25256):
   reg_z/reg_hi/reg_lo/reg_persist + interacciones momentum/flujo x régimen,
   vwap_dist_24, Garman-Klass y salto de apertura (`/tmp/vol_apply_dir_regime.py`).
   dir_bss solo pasó −0.0175 → −0.0167: subió el score, NO el edge direccional.
3. [multi] skew/kurtosis 21d, AR(1) 21d, volumen relativo -> HECHO parcialmente
   (jump_21, gap, vmax/vmin, btc lead, cross-section).
4. [multi] batería PARAMS: loop_multi.py auto -> HECHO. El primer run quedó invalidado por
   contención de CPU (5 crash falsos) y ocultó la mejora; el re-run limpio SÍ mejoró
   (trial 11 `lr=0.02` 0.06906, trial 13 `calib=none` 0.07006 vs baseline 0.06401).
5. Comparativa final de rentabilidad por activo/clase -> HECHO (ver §5); concluye que el
   Sharpe por clase está dominado por el placebo -> sin decisión de operar todavía.
6. VAULT (una sola vez, al final): python loop.py final && python multi/loop_multi.py final
   -> NO EJECUTADO (vault_runs.log inexistente en ambos). No gastar hasta cerrar el paso 2.
7. Si vault pasa gates -> paper trading; si no -> volver a 1 (nunca retocar tras ver vault).

## 7. Lecciones ya aprendidas (no repetir)

- yfinance 1.7 devuelve columnas Capitalizadas y rate-limit 429 -> backoff + lowercase.
- sklearn 1.9 crasha con columnas constantes en un fold -> _live_cols() en strategy.py.
- pandas 3.0: groupby(level=) OK; evitar .apply innecesario.
- El L/S cross-secc aplica costos POR SÍMBOLO en bps -> dividir por 1e4.
- check_causal cuesta ~40% del eval: es el precio de la seguridad anti-leakage.
- Horizontes largos (dir 10/21) descalibran con platt sobre el 20% final del train:
  si ECE>0.03, usar calibr=none o más datos de calibración.
- Ensamblar archivos por inserciones sucesivas CRUZA bloques: preferir un solo write
  o reconstruir con head -n N + append verificado con py_compile.
- NUNCA lanzar dos `loop*.py auto` a la vez (ni dos evals en paralelo). Comparten
  `strategy*.py`, `results.tsv` y `run.log`: el 22-09 a las 04:14 quedaron dos
  `loop_multi.py auto 6` vivos -> números de trial duplicados/fuera de orden
  (4,4,5,7,6), keep/revert pisándose y timeouts fantasma por contención de CPU
  (`calib=none` y `max_depth=4` "crashearon" solo por eso). Antes de lanzar:
  `pgrep -af 'loop.py auto|loop_multi.py auto'` debe estar VACÍO.
  Reparación: `python3 /tmp/vol_repair_multi_ledger.py --apply` (renumera 1..N y
  anota las filas del racer con `[race: loop duplicado]`; backup `.bak_race`).
- Mutaciones CARAS por presupuesto: en HistGB `lr` bajo multiplica el tiempo de ajuste
  (`lr=0.02` -> 903 s vs 251-333 s de una mutación típica en crypto; presupuesto 1500 s
  en crypto y 1200 s en multi). `lr` extremo + máquina ocupada = CRASH por TIME_BUDGET.
  Si hay que elegir, priorizar `max_depth`/`min_leaf`/`l2` (más baratas).
  No tocar TIME_BUDGET (vive en prepare*.py, fijo).
- Un sweep con CRASHes por contención NO es concluyente: el `auto 6` del multi (22-09
  04:14, con 5 crashes) pareció "sin mejoras" y al repetirlo limpio apareció el trial 11
  (KEEP 0.06906). Regla: repetir en máquina ociosa antes de declarar "no hay mejora".
- MITO REFUTADO por sonda aislada (22-09 05:42-05:50, máquina ociosa): `lr=0.08` NO es
  inestable. Con `timeout 2400 python3 prepare.py dev` da rc=0 en 233 s y score 0.24270
  (< 0.24571 => descarte legitimo). Referencia idle de PARAMS best = 222 s (reproduce
  exacto trial 5). Por tanto los CRASH de los ledgers son FALSOS NEGATIVOS por
  contencion de CPU: crypto trials 7-8 y multi trials 5,6,7,8,9. NO quitar valores del
  SPACE por esto.
- PROTOCOLO ANTI-TIMEOUT-FANTASMA: 1 eval a la vez y nada pesado corriendo
  (`make -j16` de llama.cpp subio la carga a ~22 en 16 cores -> todo tarda 3-6x mas y
  el harness aborta por TIME_BUDGET). Antes de creer un CRASH, medir en aislamiento:
  parchear `PARAMS` en `strategy.py`, `timeout 2400 python3 prepare.py dev`, restaurar
  el snapshot y comparar el wall-time. Sonda: `/tmp/vol_isolated_probe.sh` (reporte en
  `/tmp/vol_probe_report.txt`). Ya ejecutada y con `strategy.py` restaurado (sha1
  6798bed... = snapshots/strategy_best.py).

## 8. Archivos

| Archivo | Rol | ¿Editable en el loop? |
|---|---|---|
| prepare.py / multi/prepare_multi.py | harness fijo | NUNCA |
| strategy.py / multi/strategy_multi.py | estrategia | único mutable |
| loop.py / multi/loop_multi.py | loop keep/revert | solo setup |
| prepare.py download / multi/download_multi.py | datos reales | solo refresh |
| results.tsv / multi/results.tsv | ledger de pruebas | append-only |
| snapshots/strategy_best.py, multi/snapshots/strategy_multi_best.py | mejor estrategia (ojo: el nombre difiere en multi/) | automático |
| report_dev.json (raíz y multi/) | última evaluación | automático |
| vault_runs.log | marca el gasto del vault | append-only |
| SYSTEM.md | esta documentación | mantener al día |
| .agent.md | catálogo de research/ + reglas | referencia |
| SYSTEM_PROMPT.md / SPECS.md / TODO.md / HANDOFF.md | rieles Vibe Coding (identidad, alcance, tareas, relevo) | flujo en `AGENTS.md`; solo 1 tarea `[EN CURSO]` a la vez |
| AGENTS.md / .cursorrules | punteros de entrada por convención (Claude Code/Cursor/Windsurf) | mantener apuntando al mismo orden de lectura |
| docs/ (project-brief, tech-stack, product-features, system-architecture, code-guidelines, progress) | base de conocimiento centralizada | actualizar al cambiar stack, features nuevas, arquitectura o alcance |

## 9. Próximo paso (propuesta de 22-09; ejecutada parcialmente — ver §10)

Cuello de botella único y compartido: `dir_bss ≤ 0`. (Re-corregido 23-09 04:20: la
corrección anterior era FALSA para crypto — el score EJECUTADO no incluye `dir_bss`:
`prepare.py:30` usa `LOOP_METRIC="vol"` por defecto y nada lo fija. Evidencia dura: trial 18
(`dir-platt`) tiene score ledger 0.25390 == vol_skill 0.13855 + exp_bss 0.11535 EXACTAMENTE,
pese a dir_bss −0.0173 → −0.0025 y netSharpe +0.437 → +1.217 -> DISCARD con score empatado.
En multi sí cuenta (default `all`, prepare_multi.py:36). Decisión pendiente: migrar crypto a
`all` (archivar ledger + re-baseline) para que keep/revert vea el gate que bloquea el vault.)
Sin dirección el L/S no cubre costos
(peor: en multi el placebo rinde más que lo real). Por eso el vault sigue bloqueado.

Propuesta concreta para el crypto H1 (una mutación = un `loop.py run "..."`):

1. Features explícitas de régimen en `build_features` (causales):
   - hora del día: `np.sin/cos(2π·hour/24)` desde el índice `ts` (los datos son H1 y la
     estacionalidad intradía de crypto es fuerte); **HECHO** — `hr_sin`/`hr_cos` presentes
      en el best (línea 107 de strategy.py, incluidos en el patch struct del trial 15 aunque
      la description del ledger no los nombra).
   - distancia a VWAP 24h: `close / (Σ(close·vol)/Σ(vol) en 24h) - 1` (rolling causal).
     **HECHO** en trial 13 (KEEP).
   - Garman-Klass en lugar de solo Parkinson: `0.5·ln(H/L)² − (2ln2−1)·ln(C/O)²`.
     **HECHO** en trial 13 (KEEP).
   - ratio de saltos: `lpark_24 − lrv_24` (ya existe el patrón en multi como `jump_21`).
     **HECHO** en trial 13 (KEEP).
2. Interacción momentum × ciclo de vol: `ret_24 · cyc_24_168` y `ret_24 · vmax_168`
   (momentum solo cuando la vol está baja / lejos del máximo).
   **HECHO** en trial 13 (KEEP) — pero dir_bss solo pasó de −0.0175 a −0.0167: insuficiente.
3. Modelo por régimen: la estrategia ganadora de research es
   `research/hidden_markov_models_for_quant_finance.ipynb` (regímenes + retornos
   específicos por estado) y `research/markov_chains_for_quant_finance.ipynb` (cadena
   de Markov ajustada por MLE sobre el signo). Implementación causal barata: 2-3 estados
   estimados SOLO con el tramo de train de cada fold (el harness entrega `Xtr` completo;
   se puede hacer el clustering dentro de `fit` y guardarlo en el modelo).
   **TESTADO y RECHAZADO** — trial 16 `regime-fit: KMeans3 por régimen en fit (solo dir)`:
   DISCARD (score sin subir; dir_bss −0.0173 → −0.0306, netSharpe +0.437 → −1.535).
   El clustering por régimen dentro de `fit` empeora dir: los 3 clusters de `lrv_24×reg_z`
   sobre el train no capturan el régimen relevante para el signo. No reintentar tal cual.
4. Validar SIEMPRE con `python loop.py run "desc"`: keep solo si el score sube.
   (cumplido: 13 y 15 fueron evaluados así)

Nota metodológica: el gate de calibración (`ECE<0.03` en dir) es independiente de tener
edge; se puede arreglar con `calib=platt` + más datos de calibración, pero mientras
`dir_bss<0` calibrar solo hace honesta la ausencia de edge — no la convierte en edge.


## 10. Resultados de la evolución (loops keep/revert, datos reales)

### CRYPTO (results.tsv root; best trial 15, score 0.25390 — 16 trials, vault sin gastar)
- Keeps: 1 baseline 0.23326 · 4 semivol/signed-flow 0.23526 · 5 calib=none 0.24571 ·
  13 `dir: régimen vol×momentum/flujo + vwap/gk/gap` 0.25256 ·
  15 `struct: pos30 + breakout168 + rratio + mom72 + rank72 + btc_lead1h` 0.25390 (actual)
- vol_skill +0.139 y exp_bss +0.115 (ambos gates OK), ECE OK en vol/exp
- **best_net_sharpe +0.437 — primer `best` con Sharpe L/S neto positivo**
  (máx histórico dev +0.730 en trial 3, pero esa config fue descartada)
- dir_bss sigue en −0.0173 (gate MAL): el edge direccional NO existe aún; el Sharpe
  positivo viene del lado vol/exp, no de predecir el signo. No confundir.
- Trials 6-12 (sweep auto) y 14 (duplicado del 13) no mejoraron.
- Trial 16 `regime-fit: KMeans3 en fit (solo dir)`: DISCARD — dir_bss −0.0173 → −0.0306,
  netSharpe +0.437 → −1.535; revertido (sha vivo == snapshot 14920f0f). Ver §9.3.

### MULTI (multi/results.tsv; best trial 14, score 0.07099 — 25 trials, vault sin gastar)
- Configuración ganadora: lr=0.02, calib=none, min_leaf=250
- vol_skill +0.013 vs HAR (gate OK), exp_bss +0.069 (gate OK)
- Trials 15-22 (re-sweep auto): TODOS DISCARD; ojo con trial 19 (min_leaf=50):
  37217 s de eval (la máquina dormida/muy cargada contamina el tiempo, no el score)
- `dir: régimen` (trial 23) y `struct: mom12-1+skew/kurt+ar1` (trial 24): DISCARD —
  en multi estas mejoras NO superan al baseline, a diferencia de crypto (13 y 15 KEEP)
- `struct-lite` (trial 25, mom12-1 riesgo-ajustado): 0.07142 > 0.07099 pero el margen
  fue 0.00043 < MIN_DELTA 0.0005 -> DISCARD y revert (regla cumplida, no bug)
- dir_bss sigue negativo (−0.0117 en el best): gate MAL en multi también
- **Comparativa de rentabilidad por clase (dev, Sharpe L/S neto single-asset):**
  crypto +0.92 > gold_futures +0.80 > gold +0.65 > equity +0.61 > silver +0.58
- **Por activo:** BTC-USD +0.92, GC=F +0.80, GLD +0.65, SPY +0.63, QQQ +0.59
- Placebo multi-seed: Sharpe ~0 en todos los horizontes (h=1: −0.14±0.14) →
  la rentabilidad no es artefacto del procedimiento
- DSR>0.95 aún no alcanzado en multi (Sharpe 0.6-0.9 con 424-1400 observaciones);
  camino: combinar señales por activo en cartera, no subir el backtest individual

### Robustez a black swans (por diseño del harness)
- 2 años H1 crypto incluyen bear 2022-23 y rally 2024-25; 33 años multi incluyen
  dot-com, 2008, COVID, 2022 — el walk-forward re-entrena cada fold
- El placebo y el DSR penalizan cualquier edge que no sobreviva al azar
- ECE + calibración Platt obligan a probabilidades honestas

## 11. Cómo seguir (operador humano)
1. `python loop.py auto 20` y `python multi/loop_multi.py auto 6` — más evolución
2. No ejecutar evaluaciones manuales en paralelo con los loops (contención de CPU
   provoca CRASH por TIME_BUDGET — visto en trials 5-9 de multi)
3. Solo UN vault al final de todo: `python loop.py final` / `python multi/loop_multi.py final`
4. Si el vault pasa gates → paper trading con el tamaño Kelly fraccional del research
5. Cada semana: refresh de datos (`download`) y re-baseline del loop

## 12. Quant Core — dos motores nuevos + comparativa de los 3 sistemas (23 Sep 2026)

Integrados desde el diseño "Rough Volatility (Markovian Lifting) + Market-Neutral":

| Módulo | Qué hace | Verificación con datos reales |
|---|---|---|
| `quant_core/rough_vol_lifting.py` (Engine A) | kernel fraccionario K_H(t)≈Σ cᵢ·e^(−xᵢt) (lifting Markoviano: n OU correlacionados ⇒ O(n) por paso en vez de O(N²)), simulación de varianza rugosa + precio, Black-76 + IV implícita, calibración de skew (H,η,ρ), benchmark del lifting, y `rolling_roughness()` = H de Hurst rodante CAUSAL | H real: crypto ∈[0.02,0.71] (media 0.37), multi ∈[0.16,0.63] (media 0.44) → RUGOSO (H<0.5), como la literatura |
| `quant_core/market_neutral.py` (Engine B) | PCA de retornos → PC1 = factor de mercado (data-driven, sin índice externo); betas por activo; pesos L/S **beta-neutral + dollar-neutral** con límites de exposición | `neutralize_weights` logra Σw=0 y Σw·β=0 exactos (verificado) |
| `quant_core/compare_systems.py` | comparador walk-forward purgado IDÉNTICO para S1/S2/S2b + placebo multi-seed + DSR + ECE + stress por épocas | placebo en BRUTO ≈0 (valida la tubería); costos por clase /1e4 |

### Definición de los 3 sistemas comparados
- **S1** = estrategia multi actual (features propias).
- **S2** = S1 **+ roughness de Engine A** (`rough_H`, `rough_H_z`, `rough_regime`, `rough_H_rank`).
- **S2b** = misma señal que S2, pero construcción de cartera **beta-neutral** (Engine B).

### Resultados (dev: 76 folds walk-forward purgado, embargo 25d, costos reales por clase)
| sistema | dir_bss | exp_bss | netSharpe@h1 | netSharpe@h21 | mejor DSR | mejor BRUTO (h) |
|---|---|---|---|---|---|---|
| S1  | −0.0537 | **+0.0656** | +0.13 | +0.23 | 0.618 (h21) | +0.73 (h1) |
| S2  | −0.0547 | +0.0623 | **+0.22** | **+0.27** | **0.690 (h21)** | +0.80 (h1) |
| S2b | −0.0547 | +0.0623 | +0.09 | +0.09 | 0.309 (h21) | **+0.86 (h1)**, +0.12 (h5) |

### Lectura honesta
1. **El roughness (Engine A) MEJORA el sistema**: +0.09 Sharpe neto en h1 y +0.04 en h21, y el mejor DSR (0.69 vs 0.62). La memoria larga (H) aporta información que las features markovianas no capturan.
2. **La construcción beta-neutral (Engine B) maximiza el alpha BRUTO** (+0.86 en h1, el más alto de los tres) **pero pierde al pagar costos**: rota más nombres ⇒ turnover mayor. Mitigación pendiente: bandas de no-trade y rebalanceo semanal en vez de diario.
3. Horas/horizontes: h=1 y h=21 son los rentables; **h=10 es negativo en los tres** (zona de ruido) ⇒ operar 1d y 21d, no 10d.
4. `exp_bss` es el único bloque donde S1 gana (+0.066 vs +0.062): la roughness no ayuda a predecir *expansión* de vol, sí el resto.
5. **Ningún sistema alcanza DSR>0.95 en dev** — se necesitan más observaciones (cartera combinada, no un activo por vez), exactamente lo que ya decía §10.
6. La dirección pura (dir_bss≈−0.05) sigue siendo el punto débil estructural de la sección cruzada.

### Batería de robustez aplicada a los 3 (todos los tests, mismo código)
- **Placebo multi-seed** (8 semillas × 4 horizontes, señales permutadas dentro de cada fecha):
  bruto = +0.08±0.14 / +0.03±0.21 / −0.01±0.21 / −0.02±0.19 (h=1/5/10/21) → **≈0: sin leakage ni deriva de mercado**;
  el neto del placebo es negativo solo por costos de turnover (firma económica correcta).
- **DSR (Deflated Sharpe)** por sistema y horizonte (ajusta por nº de pruebas).
- **ECE** de calibración por tarea; **AUC** y **BSS** contra la base por fold.
- **check_causal**: recálculo con futuro truncado en ambas estrategias (aborta si hay leakage).
- **Stress por épocas** (h=5, Sharpe neto): 2008_GFC S1 +2.36 / S2 +1.61 (**positivo en la crisis**, la vol es el edge);
  COVID_2020 S1 −0.91 / S2 −1.03; bear_2022 y vol_2024_25 = n/d en dev (**son territorio del VAULT**, no se han tocado).
- **Costos reales por clase** (crypto/equity/oro/plata/futuros) con conversión bps→fracción verificada.

### 12.1 Engine A verificado de punta a punta (números reales)
```
kernel fit RMS err = 3.33e-02 (8 factores)          # K_H ≈ Σ cᵢe^(−xᵢt)
lifting O(n)=9.0ms vs convolución O(N²)=48.2ms      # speedup 5.4x a N=504 (crece con N)
H camino Browniano 20k obs = 0.499   (esperado ~0.5)  # estimador converge
H serie vol intermitente 20k = 0.44  (esperado <0.5)  # detecta rugosidad
calibrate_skew sobre skew sintético → H=0.472 η=1.904 ρ=−0.953 rmse=0.0026 (26 bp de IV)
```
Nota práctica: para IV de strikes profundos OTM hacen falta ≥1e4 paths MC (con 3e3 el ruido
domina el precio y la inversión de IV toca el límite inferior).

### 12.2 Integración en los loops vivos (veredicto del keep/revert)
| sistema | mutación | score | veredicto |
|---|---|---|---|
| crypto H1 (trial 20) | roughness Engine A (diario→H1, lag 1d) | **0.25544** (récord previo 0.25390) | **KEEP** — netSharpe +0.458, vol_skill 0.140, exp_bss 0.115 |
| multi (trial 26) | roughness (H, z, régimen, rank) | 0.06111 < 0.07099 | DISCARD |
| multi (trial 27) | roughness v2 (solo z + rank) | 0.06269 < 0.07099 | DISCARD |

**Divergencia honesta que hay que entender**: en el comparador controlado (mismo modelo,
features con/sin roughness, medición por backtest) S2 > S1 (netSharpe +0.09 en h1, DSR 0.69
vs 0.62). En el score compuesto del harness multi (`vol_skill+exp_bss+dir_bss`), la roughness
pierde porque añade dimensionalidad al task de *regresión* de vol y mueve `dir_bss`.
⇒ Si se prioriza el backtest, la roughness entra; si se prioriza el score compuesto del
harness, no. **La decisión por backtest es la que manda para operar** (es lo que paga),
pero el loop sólo acepta mejoras del score compuesto: para incorporarla al loop habría que
cambiar `LOOP_METRIC` a un score de backtest (decisión humana, documentada aquí).

### 12.3 Bug de look-ahead detectado por `check_causal` (queda documentado)
La primera versión crypto de roughness tomaba el cierre DIARIO del propio día D para todas
las barras H1 de D ⇒ las barras de la mañana "veían" el cierre de la noche (futuro).
`check_causal` lo cazó (flags: `rough_H`, `rough_H_rank`). Arreglo: **lag de 1 día** — la
barra en el día D usa el H del último día COMPLETO anterior a D (verificado: 0 diferencias
en las 430.969 filas del test de truncado).


## 14. Evolución Continua — Mejoras de Microestructura HAR y Saltos (Trials 21 Crypto / 28 Multi)

### Novedades implementadas y validadas con el loop
1. **Descomposición Bipower Variation (BV) y Saltos Continuos**:
   - Siguiendo a Barndorff-Nielsen & Shephard (2004): $BV = \frac{\pi}{2} \sum |r_t| |r_{t-1}|$.
   - Aísla la difusión continua eliminando la componente de saltos discretos (black swans puntuales).
   - `jump_ratio = (RV - BV) / RV` acotado en $[0, 1]$: cuantifica la proporción de varianza explicada por saltos abruptos.
2. **Realized Semivariances y Signed Jumps**:
   - Descomposición asimétrica $r^+ = \max(r, 0)$, $r^- = \min(r, 0)$.
   - `signed_jump = (RSV^+ - RSV^-) / RV`: mide si la volatilidad proviene de pánicos vendedores o de squeezes alcistas.
3. **Resultados del loop Karpathy**:
   - **Crypto (Trial 21)**: **KEEP** — el score pasa de `0.25544` a **`0.25627`** (récord histórico). `vol_skill` asciende a **0.14043** y `exp_bss` a **0.11584**.
   - **Multi (Trial 28)**: **KEEP** — el score pasa de `0.07099` a **`0.07305`** (récord histórico). `vol_skill` sube a **0.01426** y `exp_bss` a **0.07000**.
   - Ambas mutaciones pasaron todos los tests causales (`check_causal` estricto con truncado temporal) y los tests de robustez / placebo.



## 13. Lecciones nuevas de la integración Quant Core (bugs que costaron horas)

1. **`np.unique(tts, return_index=True)` NO agrupa por fecha** si el panel está ordenado
   por `(sym, ts)` (sym-mayor): los "días" resultantes son trozos de UN solo símbolo y el
   "L/S cross-seccional" se convierte en una caminata secuencial por activo.
   ⇒ **Agrupar SIEMPRE con `d.groupby("tt")`** (o `.indices`). Los harnesses (`prepare.py`,
   `multi/prepare_multi.py`) ya lo hacían bien; el comparador nuevo tenía el bug.
2. **El modelo debe devolver PROBABILIDAD, no etiqueta**: un `_fit_model` que envuelve
   `mdl.predict()` (0/1) produce BSS ≈ −0.9 y Sharpe destruidos. Usar
   `predict_proba(X)[:, 1]`.
3. **Escala de las señales**: si se des-demanan las probabilidades (cross-seccional),
   el umbral debe ser `0 ± CONF_MIN`, no `0.5 ± CONF_MIN` (mezclar escalas deja el libro
   sistemáticamente en corto).
4. **Dollar-neutral estricto** (`w −= mean(w)`) antes de medir: sin eso, los días en que
   un solo lado tiene señales inyectan la deriva del mercado en el "placebo" y el gate
   miente. Con neutralidad, el placebo bruto queda ≈0 y sí mide selección.
5. **Reportar el placebo en BRUTO**: el placebo NETO es negativo por definición (paga
   turnover sin señal) y no sirve como control.
6. **Prueba de sanidad sintética** antes de correr 6 minutos: backtest en memoria con señal
   conocida (Sharpe alto) y con placebo (≈0). Cuesta 2 s y evita corridas perdidas.
7. pandas 3.x: `stack(dropna=...)` da error ⇒ usar `stack()`.
8. Paralelismo: correr una eval manual mientras el loop trabaja ⇒ CRASH por TIME_BUDGET
   (contención de CPU). Siempre secuencial.
9. **Integración viva**: las features de roughness ya están en `multi/strategy_multi.py`
   (ventana 126d) y en `strategy.py` (estimadas sobre cierre DIARIO y mapeadas a H1;
   `rough_window`=63d, sintonizable por el loop). Costo: +7.9 s (multi) y +13.3 s (crypto)
   por evaluación — despreciable frente a los ~500 s / ~250 s del total.
