"""
loop.py — Loop estilo Karpathy 'autoresearch' para trading:
  1 archivo mutable (strategy.py) · 1 harness fijo (prepare.py) · 1 métrica escalar · presupuesto fijo · keep/revert · ledger.

  python loop.py baseline              # primera corrida (registra baseline)
  python loop.py run "descripción"     # evalúa strategy.py actual; keep si mejora, si no REVIERTE
  python loop.py auto 20               # 20 iteraciones automáticas de mutación de PARAMS (sin LLM)
  python loop.py final                 # VAULT: una sola vez, con la mejor estrategia
Con un agente (Claude Code): apúntalo a program.md; él edita strategy.py y llama `loop.py run`.
"""
import os, sys, ast, re, json, csv, time, shutil, random, subprocess
# V4.1: ledger y snapshot separados por métrica (LOOP_METRIC).
# - Cripto: prepare.py usa LOOP_METRIC=vol por defecto -> ledger legacy results.tsv.
# - Si LOOP_METRIC != vol (p.ej. all/dir), se usa results_{metric}.tsv + snapshot
#   strategy_best_{metric}.py, para no mezclar scores con distinta definición
#   en best() ni romper el récord vigente. prepare.py NO se toca (riel #1):
#   el score alternativo ya lo calcula el arnés; aquí solo separamos el ledger.
METRIC = os.environ.get("LOOP_METRIC", "vol")
LEDGER, SNAP, MIN_DELTA = ("results.tsv", "snapshots", 0.0005) if METRIC == "vol" else (f"results_{METRIC}.tsv", "snapshots", 0.0005)
SNAP_BEST = os.path.join(SNAP, "strategy_best.py" if METRIC == "vol" else f"strategy_best_{METRIC}.py")
COLS = ["trial", "score", "vol_skill", "exp_bss", "dir_bss", "best_net_sharpe", "seconds", "status", "description"]


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def append(row):
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter="\t", lineterminator="\n")
        if new: w.writeheader()
        w.writerow(row)


def best():
    keeps = [r for r in read_ledger() if r["status"] == "keep"]
    return max(keeps, key=lambda r: float(r["score"])) if keeps else None


def _purge_stale_pyc():
    """Borra el bytecode cacheado de strategy.py antes de evaluar. IMPRESCINDIBLE.

    `auto` reescribe PARAMS con re.sub. Si el valor nuevo tiene el MISMO nº de caracteres
    ('0.05'->'0.02', '4'->'3') y cae en el mismo segundo que la importación previa, CPython acepta
    __pycache__/strategy.*.pyc como válido (valida por mtime-segundos + tamaño) y prepare.py
    evaluaría el código ANTERIOR: la fila del ledger quedaría con un score falso (idéntico al
    best) sin haber evaluado nunca el mutante. Ver docs/progress.md (lección del pyc obsoleto).
    """
    import glob
    for p in glob.glob(os.path.join("__pycache__", "strategy.*.pyc")):
        try:
            os.remove(p)
        except OSError:
            pass


def evaluate_once():
    _purge_stale_pyc()
    env = dict(os.environ, VOL_N_TRIALS=str(len(read_ledger()) + 1))
    if METRIC != "vol":
        env["LOOP_METRIC"] = METRIC   # propaga la métrica al arnés hijo (prepare.py lee LOOP_METRIC)
    p = subprocess.run([sys.executable, "prepare.py", "dev"], capture_output=True, text=True, env=env)
    open("run.log", "w").write(p.stdout + "\n" + p.stderr)
    line = [l for l in p.stdout.splitlines() if l.startswith("SUMMARY_JSON:")]
    return json.loads(line[0][13:]) if line else None


def run(desc):
    os.makedirs(SNAP, exist_ok=True)
    n = len(read_ledger()) + 1
    s = evaluate_once()
    if s is None:
        append(dict(trial=n, score=0, vol_skill=0, exp_bss=0, dir_bss=0, best_net_sharpe=0, seconds=0,
                    status="crash", description=desc + " | ver run.log"))
        print("CRASH (ver run.log)"); revert(); return
    b = best()
    ok = (b is None) or (s["score"] > float(b["score"]) + MIN_DELTA)
    append(dict(trial=n, score=f"{s['score']:.5f}", vol_skill=f"{s['vol_skill']:.5f}", exp_bss=f"{s['exp_bss']:.5f}",
                dir_bss=f"{s['dir_bss']:.5f}", best_net_sharpe=f"{s['best_net_sharpe']:.3f}",
                seconds=f"{s['seconds']:.0f}", status="keep" if ok else "discard", description=desc))
    if ok:
        shutil.copy("strategy.py", SNAP_BEST)
        print(f"KEEP  score={s['score']:.5f}  ({desc})")
    else:
        print(f"DISCARD score={s['score']:.5f} <= best {b['score']}  ({desc})"); revert()


def revert():
    if os.path.exists(SNAP_BEST):
        shutil.copy(SNAP_BEST, "strategy.py")


def auto(n):
    import importlib.util
    _purge_stale_pyc()          # el import de PARAMS no debe leer bytecode obsoleto
    for i in range(n):
        spec = importlib.util.spec_from_file_location("strategy_probe", "strategy.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        params = dict(m.PARAMS); k = random.choice(list(m.SPACE))
        params[k] = random.choice([v for v in m.SPACE[k] if v != params[k]] or m.SPACE[k])
        src = open("strategy.py").read()
        src = re.sub(r"^PARAMS = .*$", "PARAMS = " + repr(params), src, count=1, flags=re.M)
        open("strategy.py", "w").write(src)
        print(f"[auto {i+1}/{n}] {k} -> {params[k]}")
        run(f"auto: {k}={params[k]}")


def final(force=False):
    if os.path.exists("vault_runs.log") and not force:
        sys.exit("El vault YA se usó. Repetirlo lo invalida (data snooping). Usa --force solo si lo entiendes.")
    if METRIC != "vol":
        sys.exit(f"final() solo permitido con LOOP_METRIC=vol (actual: {METRIC}). El vault se evalúa una sola vez con la métrica oficial.")
    revert()
    p = subprocess.run([sys.executable, "prepare.py", "vault"], text=True, capture_output=True,
                       env=dict(os.environ, VOL_N_TRIALS=str(len(read_ledger()) + 1)))
    print(p.stdout, p.stderr[-2000:])
    open("vault_runs.log", "a").write(time.strftime("%F %T") + " vault ejecutado\n")


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "baseline": run("baseline")
    elif c == "run": run(sys.argv[2] if len(sys.argv) > 2 else "sin descripción")
    elif c == "auto": auto(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif c == "final": final("--force" in sys.argv)
