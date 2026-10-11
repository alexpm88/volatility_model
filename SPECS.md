# SPECS.md — Especificaciones del Sistema Cuantitativo de Volatilidad

---

## 1. Visión y Objetivos del Proyecto

El sistema es un **motor predictivo y de ejecución de trading algorítmico multi-activo**, diseñado para extraer primas de riesgo de volatilidad (VRP), predecir expansiones/compresiones de volatilidad y posicionarse en la sección cruzada de activos de forma neutral al mercado.

### Activos Soportados:
1. **Criptoactivos (H1)**: 50 pares en KuCoin (BTC, ETH, SOL, altcoins líquidas) con datos horarios de alta frecuencia.
2. **Multi-Activo Diario (1D)**:
   - **Equities / Índices**: `SPY` (S&P 500, desde 1993), `QQQ` (Nasdaq 100, desde 1999).
   - **Metales Preciosos**: `GLD` (Oro ETF), `GC=F` (Futuros de Oro CME), `SLV` (Plata ETF), `SI=F` (Futuros de Plata CME).
   - **Mineras de Oro**: `GDX` (Market Vectors Gold Miners).
   - **Cripto Benchmark**: `BTC-USD` (histórico diario desde 2014).

---

## 2. Motores Cuantitativos Principales

### A. Engine A: Rough Volatility vía Markovian Lifting (`quant_core/rough_vol_lifting.py`)
- **Fundamento Matemático**: Modela la volatilidad no markoviana con exponente de Hurst $H < 0.5$ (dinámica rugosa / rough).
- **Aproximación de Bayer-Breneis / Abi Jaber**: Aproxima el kernel fraccionario fraccionario $K_H(t)$ mediante una suma de $n$ procesos Ornstein-Uhlenbeck:
  $$K_H(t) \approx \sum_{i=1}^n c_i e^{-x_i t}$$
- **Aceleración**: Reduce la complejidad de simulación de $O(N^2)$ a $O(n)$, permitiendo calibración rápida del skew en opciones y estimación causal del régimen $H$ rodante.
- **Features Generadas**: `rough_H`, `rough_H_z`, `rough_regime`, `rough_H_rank`.

### B. Engine B: Marco Market-Neutral & Factor PCA (`quant_core/market_neutral.py`)
- **PCA Cross-Seccional**: Extrae el primer componente principal (PC1) de la matriz de retornos como el factor de riesgo sistemático del mercado.
- **Beta Idiosincrático**: Regresión rolling de retornos contra PC1 para estimar $\beta_i$.
- **Optimizador de Pesos Neutrales**: Resuelve asignaciones óptimas $w_i$ cumpliendo:
  - Dollar-neutrality: $\sum_{i} w_i = 0$
  - Beta-neutrality: $\sum_{i} w_i \beta_i = 0$
  - Control de apalancamiento bruto y concentración máxima.

### C. Descomposición de Saltos HAR (Barndorff-Nielsen & Shephard)
- **Bipower Variation (BV)**: Medida continua asintótica inmune a saltos finitos:
  $$\text{BV} = \frac{\pi}{2} \sum |r_t| |r_{t-1}|$$
- **Jump Ratio**: $\max\left(0, \frac{\text{RV} - \text{BV}}{\text{RV}}\right)$ para alertar shocks abruptos de liquidez.
- **Signed Realized Semivariance**: Descompone la volatilidad en componentes direccionales alcistas y bajistas para anticipar desequilibrios de oferta/demanda.

---

## 3. Protocolo de Validación y Puertas de Aceptación (Gates)

Cada estrategia debe evaluarse en un esquema **Walk-Forward Purgado con Embargo**:
- Folds cronológicos rodantes (76 folds en multi-activo, 20 en crypto).
- Embargo temporal entre train y test para evitar leakage por autocorrelación.
- **Score Compuesto**:
  $$\text{Score} = w_1 \cdot \text{vol\_skill} + w_2 \cdot \text{exp\_bss} + w_3 \cdot \text{dir\_bss} + w_4 \cdot \text{netSharpe}$$
- **Gates Obligatorios**:
  1. `vol_skill > 0` vs modelo HAR-RV benchmark.
  2. `exp_bss > 0` (Brier Skill Score en expansión de vol).
  3. `check_causal` = PASS (0 discrepancias en truncado temporal).
  4. Placebo Test: Señales permutadas deben arrojar Sharpe bruto $\approx 0$.
  5. Resistencia a Black Swans: Evaluación en crisis (2008, 2020).
