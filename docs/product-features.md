# Product Features — Catálogo Cuantitativo de Señales y Modelos

Este documento compila el inventario exhaustivo de features, transformaciones estadísticas, modelos estocásticos y generadores de señales implementados y validados en el sistema.

---

## 1. Features de Volatilidad y Microestructura

### A. Volatilidad Realizada Multi-Escala (Cierre-Cierre)
- **Horizontes**:
  - Cripto (H1): 6h, 24h (1d), 168h (1 semana), 720h (1 mes).
  - Multi-Activo (1D): 5d (semanal), 21d (mensual), 63d (trimestral), 252d (anual).
- **Cálculo Causal**: $\text{lrv}_w = \ln\left(\sqrt{\frac{1}{w}\sum_{i=0}^{w-1} r_{t-i}^2} + \epsilon\right)$.
- **Ciclos de Volatilidad**: Spreads entre escalas temporales (`cyc_6_24`, `cyc_24_168`, `cyc_168_720` / `cyc_5_21`, `cyc_21_63`). Capturan el régimen de memoria corta vs memoria larga.

### B. Volatilidad de Rango Extremo (Parkinson & Garman-Klass)
- **Parkinson**: Basado en el log-ratio High/Low, captura la varianza intradía con 5 veces mayor eficiencia que el cierre-cierre:
  $$\sigma_{\text{park}}^2 = \frac{(\ln(H/L))^2}{4 \ln 2}$$
- **Garman-Klass**: Incorpora saltos entre apertura y cierre:
  $$\sigma_{\text{GK}}^2 = 0.5 \left(\ln(H/L)\right)^2 - (2\ln 2 - 1) \left(\ln(C/O)\right)^2$$
- **Feature de Salto**: Discrepancia entre Parkinson/GK y cierre-cierre (`jump_24`, `jump_21`). Valores altos señalan actividad concentrada en mechas intradía.

### C. Descomposición de Saltos HAR (Barndorff-Nielsen & Shephard)
- **Bipower Variation (BV)**: Medida robusta de difusión continua que aísla los saltos discretos:
  $$\text{BV} = \frac{\pi}{2} \sum_{i=1}^w |r_i| |r_{i-1}|$$
- **Jump Ratio (`jump_ratio_24` / `jump_ratio_21`)**: Fracción de varianza explicada por discontinuidades:
  $$\text{jump\_ratio} = \max\left(0, \frac{\text{RV} - \text{BV}}{\text{RV} + \epsilon}\right)$$
- **Signed Realized Semivariance (`signed_jump`)**: Diferencia entre variabilidad al alza ($r > 0$) y a la baja ($r < 0$):
  $$\text{signed\_jump} = \frac{\text{RSV}^+ - \text{RSV}^-}{\text{RV} + \epsilon}$$
  Discrimina shocks de pánico bajista de explosiones de liquidez alcista.

### D. Vol-of-Vol y Distancia a Extremos
- **Volatilidad de la Volatilidad (`vov_168` / `vov_63`)**: Desviación estándar rodante de la propia volatilidad realizada.
- **Distancia a Máximos/Mínimos (`vmax`, `vmin`)**: Mide el grado de compresión o agotamiento de la volatilidad actual respecto a los picos históricos recientes.

---

## 2. Rough Volatility — Markovian Lifting (Engine A)

- **Exponente de Hurst Rodante (`rough_H`)**:
  Calculado causalmente sobre ventanas de 63 a 126 días mediante análisis de escalamiento de varianza de incrementos:
  $$\mathbb{E}[|r_t(\Delta)|^2] \propto \Delta^{2H}$$
  Valores típicos en mercados líquidos: $H \in [0.10, 0.20]$ (extremadamente rugoso).
- **Z-Score de Rugosidad (`rough_H_z`)**: Normalización estadística de $H$ frente a su historia de 1 año.
- **Detección de Régimen Rugoso (`rough_regime`)**: Flag binario que se activa cuando $H$ colapsa por debajo de la media histórica, alertando inestabilidad estructural inminente y ensanchamiento de colas.

---

## 3. Dinámica Cross-Seccional & Market-Neutral (Engine B)

- **Factor de Mercado Latente (PC1)**: Estimado mediante Descomposición en Valores Singulares (SVD) sobre la matriz de retornos normalizada del universo.
- **Betas Dinámicos ($\beta_i$)**: Sensibilidad de cada activo respecto a PC1 calculada en ventanas rodantes purgadas.
- **Asignación Beta-Neutral y Dollar-Neutral**:
  Pesos que maximizan la exposición a las señales alfa residuales garantizando:
  $$\sum_{i=1}^N w_i = 0 \quad \text{y} \quad \sum_{i=1}^N w_i \beta_i = 0$$
- **Indicadores de Amplitud (*Breadth*) y Fuerza Relativa**:
  - `breadth_1`: Porcentaje de activos en el universo con retorno positivo en el periodo.
  - `rank_ret`, `rank_rv`: Posición percentil de cada activo en la sección cruzada en retornos y en volatilidad.
  - `rel_ret`, `rel_rv`: Exceso de retorno y de volatilidad respecto a la media del mercado.

---

## 4. Modelos Predictivos y Calibración

1. **Predicción de Nivel de Volatilidad (`task="vol"`)**:
   - Algoritmo: `HistGradientBoostingRegressor`.
   - Métrica Objetivo: `vol_skill` (reducción de error MSE comparado contra el benchmark HAR-RV causal).
2. **Predicción de Expansión de Volatilidad (`task="exp"`)**:
   - Algoritmo: `HistGradientBoostingClassifier` con calibración de probabilidad Platt / Isotónica.
   - Métrica Objetivo: Brier Skill Score (`exp_bss`), Área bajo la curva ROC (`AUC`) y Error de Calibración Esperado (`ECE < 0.03`).
3. **Predicción de Dirección de Precio (`task="dir"`)**:
   - Clasificación de retornos futuros positivos vs negativos.
   - Métrica Objetivo: `dir_bss` y Sharpe neto tras costes transaccionales reales.

---

## 5. Volume-Price Accumulation/Distribution Regime (P5.9)

### A. Features de Volumen (per-asset, causal)

- **`lv` (Log Volume Change)**: $\ln(V_t / V_{t-1})$ — variación porcentual de volumen día a día. Shift(1) garantiza causalidad (no look-ahead).
- **`volume_zscore_21`**: Z-score del volumen actual vs media/std de 21 dias. Detecta spikes de liquidez (> 1.5σ) o deshidratacion (< 0).
- **`vol_price_corr_21`**: Correlacion rodante (21d, min 14) entre retornos y cambios de volumen. Positiva = tendencia confirmada; Negativa = divergence (price-up + vol-down = distribucion; price-down + vol-up = capitulacion).
- **`acc_dist_score`**: Score de acumulacion/distribucion por activo: sign(lr) * sign(lv) * |lr| * max(0, vol_zscore_21). price-up+vol-up = acumulacion (positivo); price-down+vol-up = distribucion (negativo); sin confirmacion de volumen = ~0.

### B. Trigger de Régimen de Mercado (`acc_dist`)

En `backtester.py` `_in_bear_regime`, el trigger `acc_dist` detecta régimen de mercado usando el proxy cross-sectional (mediana del panel, o `regime_series`/`regime_volume_series` si se provee):
- **Distribucion** (cash): precio < MA(regime_window) AND volumen > avg + k*std. (price-down + volume-up = smart money distribuyendo)
- **Acumulacion** (stay invested): precio >= MA AND volumen > avg + k*std. (price-up + volume-up = smart money acumulando)
- `regime_k` (default 1.5) = umbral de z-score de volumen para confirmar el régimen.

### C. Integracion en el Composite Score

`rank_and_select_top_k` incluye `acc_dist_score` como factor cross-seccional (peso 0.10; pesos existentes reducidos 10% proporcionalmente para acomodar). El score se valida como dropna requerido.
