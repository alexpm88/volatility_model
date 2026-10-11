#!/usr/bin/env bash
# run_trial.sh — Lanzador estandarizado V4.2 (infra, NO toca prepare*.py ni loop*.py).
# Fija de raíz los dos fallos operativos detectados:
#   1. Bytecode obsoleto  -> PYTHONDONTWRITEBYTECODE=1 + purga __pycache__ pre-trial.
#   2. Logs bufferizados  -> python3 -u (stdout sin buffer) + monitor con estado en /tmp.
# Además: guarda anti-paralelo (un solo prepare* pesado a la vez, ver docs/tech-stack.md §4.1).
#
# Uso:
#   ./run_trial.sh "descripcion del trial"                       # cripto, métrica vol (UN trial; auto N va directo a loop.py)
#   LOOP_METRIC=all ./run_trial.sh "descripcion"                 # cripto, ledger all
#   ./run_trial.sh --multi "descripcion"                         # multi-activo diario (UN trial)
#   ./run_trial.sh --log mi_trial.log "descripcion"              # log explícito
#   ./run_trial.sh --wait "descripcion"                          # bloquea hasta el veredicto
#   ./run_trial.sh --force "descripcion"                         # salta el guarda anti-paralelo
# NOTA: solo envuelve `loop*.py run` (un trial). `auto N` muta PARAMS en bucle y
# debe lanzarse directo con el entorno fijado:
#   PYTHONDONTWRITEBYTECODE=1 LOOP_METRIC=vol nohup python3 -u loop.py auto 10 > auto.log 2>&1 &
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
MULTI=0; WAIT=0; FORCE=0; LOG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --multi) MULTI=1; shift;;
    --wait)  WAIT=1; shift;;
    --force) FORCE=1; shift;;
    --log)   LOG="$2"; shift 2;;
    -h|--help)
      sed -n '2,13p' "$0"; exit 0;;
    --*) echo "flag desconocida: $1" >&2; exit 2;;
    *) break;;
  esac
done
DESC="${1:-}"; [[ -z "$DESC" ]] && { echo "uso: $0 [--multi] [--wait] [--force] [--log F] \"descripcion\"" >&2; exit 2; }

if [[ $MULTI -eq 1 ]]; then
  DIR="$HERE/multi"; LOOP="loop_multi.py"; LEDGER="results.tsv"; SNAP="snapshots/strategy_multi_best.py"; STRAT="strategy_multi.py"
  METRIC="${LOOP_METRIC:-all}"
else
  DIR="$HERE"; LOOP="loop.py"
  METRIC="${LOOP_METRIC:-vol}"
  if [[ "$METRIC" == "vol" ]]; then LEDGER="results.tsv"; SNAP="snapshots/strategy_best.py";
  else LEDGER="results_${METRIC}.tsv"; SNAP="snapshots/strategy_best_${METRIC}.py"; fi
  STRAT="strategy.py"
fi
TS="$(date +%Y%m%d_%H%M%S)"
[[ -z "$LOG" ]] && LOG="$DIR/trial_${TS}.log"
STATUS="/tmp/run_trial_${TS}.status"

# 1. Guarda anti-paralelo: ningún prepare* pesado en curso (salvo --force).
# NOTA: el patrón debe coincidir con el binario real (p.ej. ".../bin/python3 prepare.py dev").
if [[ $FORCE -eq 0 ]] && pgrep -af 'prepare\.py dev|prepare_multi\.py dev' 2>/dev/null | grep -qv pgrep; then
  echo "REHUSADO: hay un prepare* en curso (tech-stack §4.1: secuencialidad obligatoria). Usa --force si sabes lo que haces." >&2
  pgrep -af 'prepare\.py dev|prepare_multi\.py dev' | grep -v pgrep >&2 || true
  exit 3
fi
# 2. Base limpia: strategy == su snapshot (evita evaluar un mutante huérfano de otra sesión).
if [[ -f "$DIR/$SNAP" ]] && ! diff -q "$DIR/$SNAP" "$DIR/$STRAT" >/dev/null 2>&1; then
  echo "REHUSADO: $STRAT difiere de $SNAP (mutante huérfano). Restaura antes: cp $SNAP $STRAT" >&2
  exit 4
fi
# 3. Purga de bytecode (cinturón + tirantes sobre _purge_stale_pyc) + entorno fijado.
find "$DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
[[ $MULTI -eq 0 ]] && export LOOP_METRIC="$METRIC"
L0=0; [[ -f "$DIR/$LEDGER" ]] && L0=$(wc -l < "$DIR/$LEDGER")

# 4. Lanzamiento desacoplado + monitor setsid con estado incremental en /tmp.
(
  cd "$DIR" && setsid nohup python3 -u "$LOOP" run "$DESC" > "$LOG" 2>&1 &
  LOOPPID=$!
  echo "PID=$LOOPPID LOG=$LOG LEDGER=$LEDGER STATUS=$STATUS START=$TS" | tee "$STATUS"
  ( while kill -0 "$LOOPPID" 2>/dev/null; do
      LC=$L0; [[ -f "$DIR/$LEDGER" ]] && LC=$(wc -l < "$DIR/$LEDGER")
      echo "$(date +%T) RUNNING ledger_lines=$LC base=$L0 tail=$(tail -1 "$LOG" 2>/dev/null | cut -c1-120)" >> "$STATUS"
      sleep 30
    done
    wait "$LOOPPID"; RC=$?
    LC=$L0; [[ -f "$DIR/$LEDGER" ]] && LC=$(wc -l < "$DIR/$LEDGER")
    VERDICT=$(grep -aE 'KEEP|DISCARD|CRASH' "$LOG" 2>/dev/null | tail -1)
    if diff -q "$DIR/$SNAP" "$DIR/$STRAT" >/dev/null 2>&1; then ST="IDENTICOS_ESTADO_LIMPIO"; else ST="DIFIERE_REVISAR"; fi
    { echo "FINISHED $(date '+%F %T') rc=$RC ledger_lines=$LC"; echo "VERDICT: $VERDICT"; echo "REVERT: $ST"; } >> "$STATUS"
  ) & disown
  echo "TRIAL LANZADO pid=$LOOPPID log=$LOG status=$STATUS"
  if [[ $WAIT -eq 1 ]]; then wait "$LOOPPID"; RC=$?; tail -2 "$STATUS"; exit "$RC"; fi
)
