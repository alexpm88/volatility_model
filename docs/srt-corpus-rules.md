# SRT Corpus — Reglas, Algoritmos y Métodos (22 videos → 77k palabras)

> **Origen**: `research/srt_corpus/*.txt` (de `.srt` en `/home/perh2x/Downloads`; 26 ficheros → 22 únicos, 3 dupes md5 eliminados).
> **Extracción**: 2026-10-04. **Criterio de código**: causalidad estricta + contrato `build_features/fit` + novedad informativa (progress.md §3.7).

## 1. Taxonomía por video (regla → veredicto)

### A. Volatilidad (núcleo)
| Video | Regla implícita | Veredicto |
|---|---|---|
| **Master ARCH & GARCH** | GARCH(1,1): varianza recursiva; clustering, leverage, kurtosis; persistencia α+β y half-life; GARCH ⊃ ARCH(∞) parsimonioso | **APLICABLE → `quant_core/garch_features.py`** (el sistema tiene HAR/bipower/roughness pero NO clustering paramétrico) |
| **Markovian Lifting Rough Vol** | Kernel fraccional ≈ Σ c_i·e^{-x_i·t} (n OU); N²→lineal; recupera FFT/afinidad | **YA PRESENTE** (Engine A `rough_vol_lifting.py` es exactamente esto) |
| **Brownian Motion** | BM/GBM como motor; incrementos independientes; base de Black-Scholes | **YA PRESENTE** (fundamento de HAR/RV; sin feature accionable) |
| **5 Papers (Bachelier→BS→Dupire→Carr-Madan)** | Difusión → sonrisa local-vol → calibración FFT con función característica | **NO APLICABLE** (pricing de opciones; el sistema es L/S predictivo) |
| **Modeling Tail Risk** | Colas leptocúrticas; VaR subestima; supervivencia > predicción; hedge convexo en drawdowns | **CERRADO con evidencia** (Trial 22 falsó VaR+tail_fatness: `0.25604`) |

### B. Estado latente / regímenes
| Video | Regla implícita | Veredicto |
|---|---|---|
| **Kalman Mean Reversion** | OU + Kalman escalar: media adaptativa (trade-off modelo-vs-dato); z vs banda; sin almuerzo gratis | **APLICABLE → `quant_core/kalman_features.py`** (el sistema NO tiene reversión adaptativa) |
| **Backtests & Markov Property** | Procesos no-markovianos exigen estado expandido; condicional ≠ incondicional | **YA PRESENTE** (rough_regime, jump_ratio, breadth; walk-forward purgado) |
| **Hedge fund Markov regimes** | 3 estados (bull/side/bear 20d) + transición pegajosa | **REDUNDANTE** (cubierto por rough_regime + mkt_ret_21; sería dilución) |

### C. Microestructura / niveles
| Video | Regla implícita | Veredicto |
|---|---|---|
| **Volume Profile** | POC, VAH/VAL (value area 70%), HVN (imán) vs LVN (rápido); bounce/reversión/breakout | **APLICABLE → `quant_core/volume_profile.py`** (POC/VA rodantes 21/63d con OHLC+V diaria; sin footprint intradiario) |
| **VWAP ×2 + Banks** | VWAP rollover = fair value; stretch → reversión; anchored en ATH/eventos; rutina liquidez→VWAP→sesión→estructura | **APLICABLE (parcial) → `quant_core/vwap_features.py`** (la parte sesión/estructura intradiaria NO es portable a diario) |
| **SuperTrend oro 35%→75%** | ATR×mult como guardarraíl; orden medir→optimizar→validar→simular→automatizar | **APLICABLE con restricción → `quant_core/supertrend_features.py`** (mult FIJO=3, ATR 10: scanear en el loop sería sobreajuste) |
| **Soporte/Resistencia + volumen** | Zonas no líneas; la REACCIÓN al test > el toque; pico de volumen = corrección | **APLICABLE (parcial)** → distancia a max/min + `dvol_21` (ya existe); resto discrecional |
| **GEX / gamma flip** | Dealers delta-neutral obligados; gamma+ amortigua, gamma− amplifica; muros, expected moves | **NO APLICABLE** (requiere cadena de opciones; no existe en ningún universo) |

### D. Validación / sizing / gestión
| Video | Regla implícita | Veredicto |
|---|---|---|
| **Does ML Improve (walk-forward)** | Meta-labeling (base→ML filtra); triple-barrier; doble overfit; walk-forward 2 niveles; p=0.06 | **YA PRESENTE + ADVERTENCIA**: el arnés YA es walk-forward purgado; meta-labeling encima = doble overfit (el video lo advierte). No implementar |
| **Power Transformers (+20% R2)** | Box-Cox (1964, λ, sólo >0) → Yeo-Johnson (2000, maneja ≤0); `PowerTransformer` + standardize; fit sólo en train | **NO-OP documentado**: `HistGradientBoosting` es invariante a transformaciones monótonas — Yeo-Johnson no cambiaría ni un split. Cero código |
| **Kelly Criterion** | f* = edge/odds; log-óptimo; error de estimación destruye (71%→41%); half-Kelly + cap | **APLICABLE (utilidad) → `quant_core/kelly_sizing.py`** (función pura de sizing, NO toca backtests del arnés) |
| **Alpha/Beta/Secret/Delusion** | Alpha = retorno ORTOGONAL; beta≠alpha; edge 1-trade ≠ edge temporal; no ergodicidad | **YA PRESENTE** (Engine B beta-neutral, placebo vs beta, caveat +0.23). Sin código |
| **Covered Calls 25y** | Coste de oportunidad del upside; collar/calendar sin vender; momentum lumpy | **NO APLICABLE** (requiere opciones; sistema L/S de spot) |

## 2. Matriz de implementación (sesión 2026-10-04)

| Módulo nuevo | Fuente | Features causales | Trial |
|---|---|---|---|
| `quant_core/garch_features.py` | ARCH/GARCH | `garch_var`, `garch_persist`, `garch_halflife`, `garch_news`, `garch_gap` | M3.5 (multi Trial 33) |
| `quant_core/kalman_features.py` | Kalman | `kalm_level`, `kalm_gain`, `kalm_z`, `kalm_slope` | M3.5 |
| `quant_core/volume_profile.py` | Volume Profile + Banks | `poc_dist_21/63`, `in_va_21/63`, `va_width_21/63` | M3.5 |
| `quant_core/vwap_features.py` | VWAP ×2 + Banks | `vwap_dist`, `vwap_stretch`, `vwap_accept`, `avwap_dist` | M3.5 |
| `quant_core/supertrend_features.py` | SuperTrend oro | `st_dir`, `st_dist`, `st_flips_21` (mult FIJO=3, ATR 10) | M3.5 |
| `quant_core/kelly_sizing.py` | Kelly | `kelly_fraction()` pura (half-Kelly + cap 0.25); fuera del loop | — (utilidad; no toca el arnés) |

**Portabilidad de lo discrecional**: ventana rodante + `shift(1)` en cruces de frecuencia; sin intradiario (footprint, sesión, GEX) ni opciones; sin optimizar parámetros en el loop (mult/ventanas fijos y documentados).

## 3. Calendario y sesiones (sesión 2026-10-04, respuesta a revisión)

**Estado previo (cíclico)**: `dw_sin/cos` (día-semana), `m_sin/cos` (día-mes, difumina el corte de mes), `mo_sin/cos` (mes-año), + `gap` (sesión nocturna open vs prev-close), `body`/`range`/`close_pos` (anatomía intradía de la vela diaria).

**Añadido (Trial 34 / M3.6)** — 5 features **duro** de calendario, función pura del timestamp ⇒ causal por construcción:

| Feature | Definición | Captura |
|---|---|---|
| `is_mon` | `dayofweek == 0` | efecto lunes (apertura de semana) |
| `is_fri` | `dayofweek == 4` | efecto viernes (cierre de semana) |
| `is_mstart` | `día <= 3` | primeros días de mes (flujos de fondos, rebalanceos) |
| `is_mend` | `día > dim - 3` | últimos días de mes (window-dressing, roll) |
| `mend_dist` | `(dim - día) / dim` ∈ [0,1] | proximidad suave al cierre de mes |

**NO portable — volumen por sesión NY (apertura/cierre) vs otras sesiones**: la intuición es correcta (el volumen de la apertura/cierre de NY **no** es el de Londres/Tokio), pero el panel multi es **diario** (9.841 ts, delta mediano = 1d, hora=0): cada barra trae **un único volumen/día**. Separarlo por sesión exige datos intradía (H1/M1) que el arnés no tiene. El proxy diario existente ya captura la sesión de forma agregada: `gap` (overnight) y `body`/`close_pos` (sesión regular). **Para sesiones explícitas habría que re-descargar el panel en H1** (coste: ~24× filas, re-tuneo de ventanas en unidades de barras, posible incompatibilidad con snapshots vigentes) — fuera del alcance de esta iteración.
