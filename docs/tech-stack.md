# Tech Stack & Environment — Volatility Model

---

## 1. Entorno de Ejecución Base

- **Sistema Operativo**: Linux (Arch Linux / EndeavourOS x86_64).
- **Kernel**: Linux 6.x.
- **Intérprete de Python**: Python 3.14 (Mise / Pyenv management).
- **Ruta Base del Repositorio**: `/run/media/perh2x/Projectos/volatility_model`.
- **Ejecución de Tareas**: Procesos en segundo plano vía `nohup` o subprocesos independientes con captura de logs y control de PID.

---

## 2. Librerías Cuantitativas y Versiones de Referencia

| Librería | Propósito Principal | Buenas Prácticas & Restricciones |
|---|---|---|
| **`numpy`** | Operaciones numéricas vectorizadas, álgebra lineal y convoluciones | Evitar bucles `for` en series temporales. Usar broadcasting y operaciones in-place cuando sea posible. |
| **`pandas`** | Manejo de paneles MultiIndex `(sym, ts)` y series temporales | Usar siempre `groupby(level="sym")` para operaciones causales individuales. Prohibido usar `stack(dropna=...)` en pandas 3+. |
| **`scipy`** | Optimización (`least_squares`), distribuciones (`norm`, `t`), tests estadísticos | Utilizado en la calibración del kernel de Ornstein-Uhlenbeck y en el cálculo de p-valores y ratios de información. |
| **`scikit-learn`** | Modelos predictivos (`HistGradientBoostingClassifier`, `HistGradientBoostingRegressor`) | Soportan NaNs nativamente. Regla crítica: filtrar columnas con varianza cero (`_live_cols`) para evitar fallos de binarización. |
| **`statsmodels`** | Regresiones OLS causales, modelos GARCH y análisis de residuos | Empleado para la extracción de betas en rolling windows y contrastes de estacionariedad. |
| **`yfinance`** | Ingesta de datos de renta variable, ETFs y materias primas (CME/Yahoo) | Descarga automática en `multi/download_multi.py` con reintentos y almacenamiento persistente en caché pickle. |
| **`ccxt`** | Conexión con exchanges de criptoactivos (KuCoin) | Manejo de límites de tasa (*rate-limiting*) y paginación causal de barras H1. |

---

## 3. Comandos de Operación y Desarrollo

### A. Entorno Cripto H1
```bash
# Lanzador estándar V4.2 (fija env + guardas + monitor en /tmp)
./run_trial.sh "descripcion del experimento"
LOOP_METRIC=all ./run_trial.sh "descripcion"   # ledger all
./run_trial.sh --multi "descripcion"           # multi-activo
./run_trial.sh --wait "descripcion"            # bloquea hasta el veredicto

# Equivalentes manuales (el lanzador los envuelve)
python3 loop.py run "descripcion del experimento"

# Bucle autónomo de optimización de hiperparámetros (ej. 10 iteraciones)
python3 loop.py auto 10

# Test manual rápido de causalidad y sanidad
python3 -c "import prepare, strategy; panel = prepare.load_panel(); prepare.check_causal(strategy, panel)"
```

### B. Entorno Multi-Activo Diario
```bash
# Actualizar datos de mercado diarios desde Yahoo Finance
python3 multi/download_multi.py

# Evaluar la estrategia multi-activo en walk-forward purgado
cd multi && python3 loop_multi.py run "descripcion del experimento"

# Bucle autónomo multi-activo
cd multi && python3 loop_multi.py auto 10
```

### C. Comparativa Global de Sistemas y Stress Testing
```bash
# Correr comparativa entre S1 (Baseline), S2 (Roughness) y S2b (Beta-neutral)
python3 quant_core/compare_systems.py dev
```

---

## 4. Política de Gestión de Recursos y Hardware

1. **Secuencialidad Obligatoria**: No ejecutar dos procesos de entrenamiento pesados (`prepare.py` o `prepare_multi.py`) en paralelo. La saturación de núcleos de CPU dispara el tiempo por fold y puede provocar abortos por timeout (`TIME_BUDGET`).
2. **Monitoreo de Procesos**: Comprobar siempre que no haya procesos zombis antes de iniciar una corrida:
   ```bash
   pgrep -af 'loop|prepare|compare_systems'
   ```
3. **Persistencia de Resultados**: Todo resultado de evaluación se anexa en formato TSV atómico a `results.tsv` (Cripto) o `multi/results.tsv` (Multi-activo).
