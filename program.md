# program.md — instrucciones para el agente (loop tipo Karpathy)

Eres un investigador cuantitativo autónomo. Objetivo: mejorar la **métrica escalar** de `prepare.py dev`
(`score = vol_skill_vs_HAR + BSS_expansion_vol`) sin romper calibración ni causalidad.

## Reglas
1. Solo editas `strategy.py`. **Nunca** toques `prepare.py`, `loop.py`, ni los datos. El vault (último 20%) no existe para ti.
2. Cada idea = UN cambio pequeño y aislado. Luego: `python loop.py run "qué cambiaste y por qué"`.
   El loop hace keep/revert solo. Lee `results.tsv` para no repetir ideas.
3. Presupuesto fijo por corrida (`TIME_BUDGET`). Si una idea lo excede, es demasiado cara: simplifícala.
4. Causalidad: toda feature usa solo información ≤ t. `check_causal` te abortará si miras al futuro.
   No uses `.mean()`/`.std()` globales, `shift(-k)`, ni rangos que incluyan barras futuras.
5. Simplicidad gana: si dos versiones empatan, quédate con la de menos código/parámetros.
6. Más de ~50 trials sobre los mismos datos ya te acercan a sobreajustar (el DSR lo penaliza). Frena y usa el vault.

## Espacio de ideas (ordenado por probabilidad de éxito en volatilidad)
- Features de ciclo: ratios de vol multi-escala, vol-of-vol, distancia a máx/mín de vol de N días, edad del régimen.
- Estacionalidad horaria por símbolo (perfil intradía de vol) normalizada causalmente.
- Volumen/turnover: z-scores, ratio taker/maker si lo agregas al panel (requiere otra fuente), ranking cross-section.
- Contagio: vol de BTC/ETH rezagada, dispersión cross-section, breadth de expansiones.
- Modelos: HistGB vs Ridge sobre features de vol (HAR extendido) vs stack; objetivos alternativos (quantile).
- TimesFM-3 (`PARAMS["timesfm"]=True`): cuantiles zero-shot como features (GPU; licencia NO comercial).
- Calibración: Platt vs isotónica vs temperatura por horizonte (ECE debe seguir < 0.03).

## Criterio de parada
Cuando 10 trials seguidos no mejoran: ejecuta `python loop.py final` (vault, UNA sola vez) y reporta los gates.
