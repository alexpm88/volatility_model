# Code Guidelines — Estándares y Patrones Requeridos/Prohibidos

---

## 1. Reglas de Prevención de Look-Ahead Bias

1. **Causalidad Temporal Obligatoria**:
   - Todo cálculo debe poder reproducirse exactamente si se desconoce por completo cualquier dato posterior a $t$.
   - Al usar funciones rodantes (`rolling`, `expanding`), verificar que no haya desfases implícitos hacia el futuro (`center=False`).
2. **Lagging al Cruzar Frecuencias (Diario a Horario)**:
   - Al calcular métricas en frecuencia diaria e interpolarlas en barras horarias (ej. la rugosidad $H$ de Engine A en el modelo cripto), es **mandatorio aplicar un `shift(1)` diario**:
     ```python
     # CORRECTO: El valor para el día D proviene exclusivamente del cierre del día D-1
     daily_feature = raw_daily_feature.shift(1).reindex(hourly_index).ffill()
     ```
   - Sin el `shift(1)`, el precio de cierre a las 23:59 del día $D$ estaría filtrándose a las barras de las 08:00 AM del mismo día $D$.

---

## 2. Convenciones de Modelado y Machine Learning

1. **Predicciones de Probabilidad**:
   - Para tareas de clasificación (`task="exp"` o `task="dir"`), el estimador **debe devolver probabilidades continuas**:
     ```python
     # OBLIGATORIO:
     probs = model.predict_proba(X)[:, 1]
     # PROHIBIDO:
     preds = model.predict(X)  # Genera etiquetas discretas 0/1 y arruina BSS y ECE
     ```
2. **Limpieza de Columnas Degeneradas**:
   - `HistGradientBoosting` en scikit-learn puede fallar si existen columnas con varianza idénticamente nula en un fold determinado. Filtrar siempre mediante `_live_cols`:
     ```python
     def _live_cols(X):
         return [c for c in X.columns if X[c].nunique(dropna=True) > 1]
     ```
3. **Manejo de Valores Infinitos y Nulos**:
   - Reemplazar siempre infinitos por NaNs antes de retornar features:
     ```python
     return F.replace([np.inf, -np.inf], np.nan).astype("float32")
     ```

---

## 3. Construcción de Portafolios y Simulación de Ejecución

1. **Costes de Transacción Realistas**:
   - Cripto Spot: 10 bps por lado (0.0010).
   - Equities (ETFs líquidos): 2 bps por lado (0.0002).
   - Futuros (Oro CME / Plata): 1 a 2 bps por lado.
   - En el código de backtest, los costos se expresan en fracción: `cost_bps / 10000.0`. Nunca olvidar la conversión a fracción.
2. **Dollar Neutrality y Beta Neutrality**:
   - En carteras long/short cross-seccionales, centrar siempre los pesos respecto a la media:
     ```python
     # Des-mediar para neutralidad en dólares exacta
     w = w - np.nanmean(w)
     ```
   - Si se aplica neutralidad de beta (Engine B), proyectar los pesos al espacio ortogonal del vector $\beta$:
     $$\mathbf{w}_{\text{neutral}} = \mathbf{w} - \frac{\mathbf{w}^T \boldsymbol{\beta}}{\|\boldsymbol{\beta}\|^2} \boldsymbol{\beta}$$

---

## 4. Filosofía de Cambios de Código (Anti-Regresión)

1. **Mutaciones Atómicas**: Realizar un cambio de hipótesis a la vez (ej. un conjunto específico de features o un hiperparámetro). No mezclar múltiples modificaciones no relacionadas en una sola iteración.
2. **Validación Pre-Ejecución**: Antes de lanzar `loop.py run`, verificar la sintaxis y compilación:
   ```bash
   python3 -m py_compile strategy.py
   ```
3. **Reversión Respetada**: Si el loop emite `DISCARD` o `CRASH`, aceptar el veredicto del árbitro y analizar el log antes de formular la siguiente hipótesis.
