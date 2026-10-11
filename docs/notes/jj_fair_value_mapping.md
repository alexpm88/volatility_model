# JJ Fair-Value / Prop-Firm Mapping → volatility_model

> **Nota de integridad (AGENTS.md L1)**: `multi/prepare_multi.py`,
> `multi/strategy_multi.py`, `multi/loop_multi.py` son **ARNÉS off-limits**
> ("El agente NO edita este archivo"). Este documento es un *mapping* y spec de
> integración, **no** una mutación del arnés. Cualquier wiring a `multi/` es
> **out-of-rieles** (requiere auth + excepción de arnés).

## 1. Qué es el transcript de JJ y por qué NO es el volatility_model

El transcript de JJ Simon describe un sistema **direccional de price-action
prop-trading sobre futuros NASDAQ (NQ)**: *fair pricing theory* (sesión open =
fair 95% de días no-news; pre-news price = fair en días news), entradas
**displacement / breakup structure**, news reversion vs. unexpected-news drift,
y una capa de gestión de posición **estática** (R/R fijo, regla de consistencia,
risk-of-ruin, costo-por-cuenta-financiada, EV de cuenta, kill-switch de 3
pérdidas, estratificación por tier de TP).

El `volatility_model` es, en cambio, un modelador **mult-asset de volatilidad
realizada** (Engine A rough vol, Engine B market-neutral, HAR jumps) sobre
**SPY/GLD/SLV/GC=F/SI=F/GDX/BTC** — su `dir_bss` (dirección 1d-ahead) es
**estructuralmente near-random (AUC ≈ 0.53)** y el gate `direccion_BSS>0` falla
2/4 horizontes (B1 true-OOS: `−0.0038 → −0.0018`, 2/4 < 3 → FAIL).

## 2. Qué SÍ aporta JJ: la capa de posición/gestión (portable)

Lo **transportable** del transcript es la **gestión de posición prop-firm**, que
NO existe en `backtest_ls` (que usa lambda vol-escalado). `jj_fair_value/positioning.py`
la codifica como **math pura, testeada** (tests pass):

| Concepto JJ | Función | Fórmula / regla |
|---|---|---|
| Risk-of-ruin: prob. de N evals seguidos perdidos | `risk_of_ruin(pass_rate, n)` | `(1 − pass_rate)^n` (L43:25-45:29) |
| Costo real por cuenta financiada | `expected_cost_per_funded(eval_cost, pass_rate)` | `eval_cost / pass_rate` (L24:26-24:49) |
| EV de una cuenta financiada | `funded_expected_value(avg_payout, payout_prob)` | `avg_payout · payout_prob` (L24:53-25:13) |
| Tier de R/R estático por clase de cuenta | `rr_tier(has_consistency, has_live_cap, pts)` | eval 1:1.5; consistency/lived 1:1.5-1:2; unlimited 1:3-1:6 (L11:01-45:01) |
| Kill-switch por sesión | `session_kill_switch(losses, max_losses=3)` | paras tras 3 perdedoras (L34:36-34:39) |
| Riesgo estático (optimiza TP primero) | `optimal_risk_static(tp, max_loss, contr, PV)` | TP=pts·PV·contr; risk=max_loss; RR=TP/risk (L57:00-59:25) |
| Estratificación por cuenta | `account_stratification(pts_to_fair)` | enruta a la cuenta con TP más próximo (L37:59, L57:12) |

> JJ optimiza **TP primero** y deja el stop "esencialmente aleatorio" (L57:49).
> `optimal_risk_static` reproduce eso: risk = max-loss del account; RR surge de TP/risk.

## 3. Qué aporta JJ: la señal direccional (referencia standalone)

`jj_fair_value/signal.py` implementa la lógica de entrada (pura, sin datos,
sin arnés) para referencia/futuro wiring:

- `fair_price_session_open` — fair = open (non-news) o pre-news price (news) (L82:45, 54:19, 61:58).
- `fair_value_bias` — signo(last − fair) → dirección de reversión (L477).
- `is_displacement` — cuerpo > cuerpo previo **y** close más allá del wick previo (L55:23, 63:31).
- `is_breakup_structure` — wick más allá de las 2 velas adyacentes + break confirmado (L54:40, 66:19).
- `expected_news_direction` — EXPECTED ≈ 0 (priced-in); UNEXPECTED = drift del sorpresa (L12:55, 14:21).
- `session_window` / `news_is_expected` — 90 min NY/London/NY-PM; schedule 8:30 red-folder (L15:07, 12:27).

## 4. Mapeo de integración (REQUERIE AUTH — out-of-rieles)

Si se autoriza el track direccional, el puente al `volatility_model` es **solo
capa de posición**, no de señal:

```
[jj_fair_value/positioning.py] -> portfolio_engine/optimizer.py
  risk_of_ruin / expected_cost_per_funded / funded_expected_value
  rr_tier / optimal_risk_static / session_kill_switch
    (NO toca multi/strategy_multi.py ni multi/prepare_multi.py — off-limits)

[jj_fair_value/signal.py] -> research/srt_corpus + engine direccional nuevo
  (direccional; NO reutiliza el score=vol_skill+exp_bss del multi — near-random)
```

- **Señal direccional (fair value/displacement)** → **nuevo engine direccional
  (out-of-rieles)**; reutilizaría `research/srt_corpus` (fair value, VWAP, estructura)
  como base de features, pero NO el `dir` gate del multi (AUC 0.53, techo).
- **Gestión de posición** → **extensión de `portfolio_engine/optimizer.py`**
  (hoy solo lambda vol-escalado); JJ aporta el marco estático/RR/consistency/risk-of-ruin.

## 5. Registro de integridad

| Ítem | Estado |
|---|---|
| `multi/strategy_multi.py` vs snapshot Trial 45 | **diff 0** (CHAMP_OK_DIFF0) |
| `multi/prepare_multi.py` editado | **NO** (diff 0; harness off-limits) |
| AUC dir (B1 true-OOS) | near-random 0.53, gate dir FAIL 2/4<3 -> techo estructural |
| `jj_fair_value/` | standalone; py_compile OK; tests pass; NO importa `multi/` |
| Auth para wiring `multi/` | **pendiente** (out-of-rieles) |

## 6. Conclusión operativa

- **Shippable final del volatility_model = V5.1+B2** (SHIPPED 09-Oct; gates 4/5
  baseline, sin regresión). JJ no lo cambia: su señal direccional no eleva
  `dir_bss>0` en este universo (AUC 0.53).
- JJ aporta **valor real en la capa de posición** (math de §2) y como **blueprint
  del track direccional out-of-rieles** (`jj_fair_value/` §3), construido,
  testado y listo — pero **NO integrado** al pipeline `multi/` hasta auth +
  excepción de arnés.

## 7. Registro del engine direccional out-of-rieles (`directional/`)

- **10-Oct 2026**: construido paquete `directional/` en repo root (paralelo a
  `jj_fair_value/` + `multi/`), 7 archivos, **importa `jj_fair_value.{signal,positioning}`
  sin mutar `multi/`**. Codifica el engine direccional completo de JJ: fair-value sesión
  open/pre-news → entrada displacement/breakup → gestión estática (R/R fijo, kill-switch
  3-loss, static risk, estrificación TP).
- **Self-test (synthetic FQV, 450 barras / 90-min sessions)**: 4/4 tests pass
  (DIRECTIONAL_COMPILE_OK); kill-switch dispara en la sesión *trend* a i=183 (3 pérdidas
  consecutivas; max_consec==3; win+loss coexistentes); `DirectionalRunner` (threaded) ==
  secuencial (determinismo preservado). El pipeline reutiliza
  `jj_fair_value.signal.fair_value_bias` + `is_displacement` + `is_breakup_structure` y
  `jj_fair_value.positioning.session_kill_switch` / `rr_tier` / `optimal_risk_static`.
- **Bug de integridad**: el OHLCV synthetic tenía columnas permutadas (high<low); corregido
  a orden `(open,high,low,close,volume)` + padding truly-flat.
- **Integridad**: `multi/strategy_multi.py`≡Trial 45 (diff 0 CHAMP_OK_DIFF0);
  `multi/prepare_multi.py`/`loop_multi.py` no editados; `NONE_RUNNING`.
- **Status**: engine listo para eval OOS con datos reales NQ. Wiring a `multi/` (score
  `vol_skill+exp_bss`) y universo NQ = **out-of-rieles** (auth + excepción de arnés L1;
  `dir_bss` near-random AUC 0.53 en universo vol del multi → no aporta al gate multiactivo,
  pero es independiente en `directional/`).
- **Shippable final vol model = V5.1+B2 (sin cambios)**; el track direccional es un
  producto independiente shippable tras OOS NQ.
