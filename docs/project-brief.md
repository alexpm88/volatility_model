# Project Brief — Sistema Cuantitativo Multi-Activo de Volatilidad

---

## 1. Resumen Ejecutivo y Tesis de Inversión

La volatilidad financiera exhibe propiedades estadísticas universales bien documentadas pero frecuentemente mal explotadas:
1. **Agrupamiento de volatilidad (*volatility clustering*)**: Grandes oscilaciones suelen seguir a grandes oscilaciones, independientemente del signo.
2. **Memoria larga y rugosidad (*roughness*)**: Las trayectorias de volatilidad son sustancialmente más rugosas que un movimiento Browniano fractal ($H < 0.5$).
3. **Asimetría y efecto apalancamiento**: Los shocks bajistas en activos de riesgo detonan expansiones de volatilidad mucho más violentas que las subidas correspondientes.
4. **Prima de Riesgo de Volatilidad (VRP)**: La volatilidad implícita demandada por los participantes del mercado de opciones supera en promedio a la volatilidad realizada subsiguiente.

El objetivo de este proyecto es construir y operar un **sistema sistemático, completamente automatizado y cuantitativamente validado**, capaz de predecir la dinámica futura de la volatilidad, clasificar regímenes de mercado y ejecutar estrategias de cobertura y captura de prima de forma neutral al mercado sobre múltiples clases de activos.

---

## 2. Universo de Activos y Justificación Económica

El sistema opera sobre tres universos complementarios para maximizar la diversificación de fuentes de riesgo:

| Clase de Activo | Símbolos Representativos | Frecuencia | Características Económicas |
|---|---|:---:|---|
| **Criptoactivos Líquidos** | BTC, ETH, SOL, XRP y 46 altcoins | H1 (Horaria) | Alta volatilidad, trading 24/7, prima de liquidez elevada, fuertes ineficiencias de corto plazo y dinámicas de liquidación forzada en cadena. |
| **Metales Preciosos & Commodities** | `GLD`, `GC=F` (Oro), `SLV`, `SI=F` (Plata), `GDX` (Mineras) | 1D (Diaria) | Activos de refugio (*safe haven*), baja correlación con acciones en eventos de estrés macroeconómico, fuerte estacionalidad y respuesta a shocks de tasas de interés reales. |
| **Renta Variable & Índices** | `SPY` (S&P 500), `QQQ` (Nasdaq 100) | 1D (Diaria) | Los mercados más líquidos del mundo, historial de datos de más de 30 años (1993-presente), ideales para pruebas de robustez contra regímenes extremos y crisis estructurales. |

---

## 3. Modelo de Negocio Cuantitativo y Extracción de Alpha

1. **Predicción de Expansión de Volatilidad (`exp_bss`)**:
   - Detectar puntos de quiebre donde la volatilidad baja comprime el mercado antes de una explosión direccional (*volatility squeeze*).
   - Monetización: Activación de opciones largas, compra de gamma o ampliación de bandas de volatilidad en sistemas de tendencia.

2. **Captura de Prima en Sección Cruzada (Long/Short Neutral)**:
   - Ordenar el universo por sobreestimación relativa de riesgo y posicionarse largo en los activos con mayor exceso de retorno ajustado por volatilidad y corto en los activos sobrevaluados o con colas explosivas desfavorables.
   - Restricción: Cartera balanceada con beta cero respecto al mercado global para no asumir exposición direccional pasiva.

3. **Gestión Dinámica de Drawdown (Protección contra Black Swans)**:
   - Escalamiento inverso de posiciones según el nivel de régimen de volatilidad (`volatility scaling`). Reducción automática de exposición en regímenes de alta turbulencia ($H$ colapsando o z-scores de vol $> 2\sigma$).

---

## 4. Filosofía de Desarrollo: Loops Rígidos vs Vibe Coding

Para evitar la degradación del código y los sesgos habituales de la investigación cuantitativa (overfitting, look-ahead bias, p-hacking), el proyecto sigue una estricta filosofía de **Specs-First y Bucle Ciego de Karpathy**:
- Los arneses de datos y backtest no son modificables.
- Toda hipótesis se traduce en una mutación mínima de features o arquitectura.
- Solo las mutaciones que superan estadística y económicamente a la incumbente son incorporadas (`KEEP`), asegurando una marcha asintótica hacia un sistema cada vez más robusto.
