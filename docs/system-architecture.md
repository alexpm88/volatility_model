# System Architecture — Flujos de Datos, Arnés y Loops

Este documento describe la arquitectura modular del sistema, los contratos de datos entre componentes y el protocolo de evaluación walk-forward purgado.

---

## 1. Diagrama de Arquitectura Global

```
                 [ FUENTES DE MERCADO ]
             KuCoin API (H1) / Yahoo Finance (1D)
                        │
                        ▼
           ┌─────────────────────────────┐
           │ INGESTA & ALMACENAMIENTO    │
           │  • raw_h1.pkl (50 criptos)  │
           │  • multi_raw.pkl (8 activos)│
           └────────────┬────────────────┘
                        │
       ┌────────────────┴────────────────┐
       │                                 │
       ▼                                 ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ ESTRATEGIA CRIPTO H1          │ │ ESTRATEGIA MULTI-ACTIVO 1D    │
│  strategy.py                  │ │  multi/strategy_multi.py      │
│  • Features locales (H1)      │ │  • Features locales (1D)      │
│  • Lead BTC, Vol cycles       │ │  • Spreads, gaps nocturnos    │
│  • Roughness Engine A (lag 1d)│ │  • Bipower Jumps, Skew/Kurt   │
│  • Bipower + Signed Jumps     │ │  • Engine B (Market Neutral)  │
└──────────────┬────────────────┘ └──────────────┬────────────────┘
               │                                 │
               ▼                                 ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ ARNÉS FIJO CRIPTO (Árbitro)   │ │ ARNÉS FIJO MULTI (Árbitro)    │
│  prepare.py                   │ │  multi/prepare_multi.py       │
│  • 20 Folds Walk-Forward      │ │  • 76 Folds Walk-Forward      │
│  • Embargo temporal (25d)     │ │  • Embargo temporal (25d)     │
│  • check_causal (Anti-leak)   │ │  • check_causal (Anti-leak)   │
│  • Placebo Multi-Seed (8 seeds│ │  • Costes reales por clase    │
│  • DSR de Blaise, ECE, AUC    │ │  • DSR, ECE, Stress Tests     │
│  • Vault sellado (20% final)  │ │  • Vault sellado (20% final)  │
└──────────────┬────────────────┘ └──────────────┬────────────────┘
               │                                 │
               ▼                                 ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ LOOP AUTÓNOMO (Karpathy)      │ │ LOOP AUTÓNOMO (Karpathy)      │
│  loop.py                      │ │  multi/loop_multi.py          │
│  • run <desc> / auto <N>      │ │  • run <desc> / auto <N>      │
│  • Snapshot & Git-like revert │ │  • Snapshot & Git-like revert │
│  • Gate: Score > Best + 0.0005│ │  • Gate: Score > Best + 0.0005│
│  • Ledger en results.tsv      │ │  • Ledger en results.tsv      │
└───────────────────────────────┘ └───────────────────────────────┘
```

---

## 2. Contratos de Datos y Paneles MultiIndex

Todos los datos se estructuran en dataframes de `pandas` con índice jerárquico bidimensional ordenado:
- **Índice**: `(sym, ts)` donde `sym` es el identificador del activo (`str`) y `ts` es una marca temporal (`pd.Timestamp`).
- **Columnas obligatorias**: `open`, `high`, `low`, `close`, `volume`.

### Regla Crítica de Agrupación
Dado que el panel está ordenado por símbolo y luego por tiempo (`sym-mayor`):
- Las agrupaciones cross-seccionales (para calcular medias del mercado, rankings o carteras neutrales) **DEBEN** realizarse explícitamente mediante:
  ```python
  d.groupby("ts")  # o d.groupby(level="ts")
  ```
- **PROHIBIDO**: Utilizar `np.unique(tts, return_index=True)` sobre paneles ordenados por símbolo, ya que toma fragmentos continuos de un único símbolo en lugar de cortar el panel transversalmente por fecha.

---

## 3. Protocolo Walk-Forward Purgado con Embargo

Para replicar de forma fidedigna la operativa real y evitar la contaminación del futuro:
1. **Purga Temporal**: Los datos de entrenamiento terminan en $t_{\text{train\_end}}$.
2. **Embargo**: Se excluyen los siguientes $E$ días (típicamente 25 días) después de $t_{\text{train\_end}}$. Esto previene que features basadas en ventanas rodantes largas (ej. 21 días) se solapen entre el conjunto de entrenamiento y el conjunto de prueba.
3. **Periodo de Prueba Causal**: El modelo entrenado genera predicciones sobre la ventana de prueba sin actualizarse internamente durante esa ventana.
4. **Desplazamiento del Fold**: La ventana se desliza en pasos fijos (`FOLD_DAYS = 63` días en multi-activo; `168` horas en cripto), acumulando predicciones *out-of-sample* continuas sobre toda la historia disponible.

---

## 4. Función de Puntuación Compuesta y Gates de Aceptación

El referee (`prepare.py`) consolida las métricas predictivas en un escalar único:
$$\text{Score} = w_{\text{vol}} \cdot \text{vol\_skill} + w_{\text{exp}} \cdot \text{exp\_bss} + w_{\text{dir}} \cdot \max(0, \text{dir\_bss}) + w_{\text{sh}} \cdot \max(0, \text{netSharpe})$$

Para que una mutación sea aceptada en el ledger (`KEEP`):
1. **`score >= best_score + 0.0005`**: Superar al campeón histórico por un margen estadísticamente significativo.
2. **`check_causal == PASS`**: Superar el test de truncado temporal (recalcular en $t_{\text{cut}}$ sin futuro debe ser idéntico al valor histórico).
3. **Cero Caídas / Crashes**: La ejecución de los 76 folds debe completarse en menos del presupuesto temporal asignado (`TIME_BUDGET`).
