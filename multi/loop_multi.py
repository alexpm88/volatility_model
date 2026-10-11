"""loop_multi.py — Loop de Karpathy para el sistema multi-activo (idéntico a loop.py).
  python loop_multi.py baseline          (desde multi/)
  python loop_multi.py run "descripción"
  python loop_multi.py auto 10
"""
import os, sys, json, csv, time, shutil, random, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
LEDGER, SNAP, MIN_DELTA = "results.tsv", "snapshots", 0.0005
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
        if new:
            w.writeheader()
        w.writerow(row)


def best():
    keeps = [r for r in read_ledger() if r["status"] == "keep"]
    return max(keeps, key=lambda r: float(r["score"])) if keeps else None


def _purge_stale_pyc():
    """Borra el bytecode cacheado de strategy_multi.py antes de evaluar. IMPRESCINDIBLE.
    Mismo bug que en loop.py: si `auto` reescribe PARAMS con el mismo nº de caracteres
    ('2'->'4', '250'->'350') en el mismo segundo que la importación previa, CPython acepta el
    .pyc (mtime-segundos + tamaño) y prepare_multi.py evaluaría el código ANTERIOR, dejando una
    fila con score idéntico al best sin evaluar el mutante (Trials 3, 4 y 10 del ledger multi).
    """
    import glob
    for p in glob.glob(os.path.join("__pycache__", "strategy_multi.*.pyc")):
        try:
            os.remove(p)
        except OSError:
            pass


def evaluate_once():
    _purge_stale_pyc()
    env = dict(os.environ, VOL_N_TRIALS=str(len(read_ledger()) + 1))
    p = subprocess.run([sys.executable, "prepare_multi.py", "dev"], capture_output=True, text=True, env=env)
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
        shutil.copy("strategy_multi.py", f"{SNAP}/strategy_multi_best.py")
        print(f"KEEP  score={s['score']:.5f}  ({desc})")
    else:
        print(f"DISCARD score={s['score']:.5f} <= best {b['score']}  ({desc})"); revert()


def revert():
    if os.path.exists(f"{SNAP}/strategy_multi_best.py"):
        shutil.copy(f"{SNAP}/strategy_multi_best.py", "strategy_multi.py")


def auto(n):
    import importlib.util
    _purge_stale_pyc()          # el import de PARAMS no debe leer bytecode obsoleto
    for i in range(n):
        spec = importlib.util.spec_from_file_location("strategy_probe", "strategy_multi.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        params = dict(m.PARAMS); k = random.choice(list(m.SPACE))
        params[k] = random.choice([v for v in m.SPACE[k] if v != params[k]] or m.SPACE[k])
        src = open("strategy_multi.py").read()
        src, cnt = re.subn(r"^PARAMS = .*$", "PARAMS = " + repr(params), src, count=1, flags=re.M)
        if cnt != 1:
            raise RuntimeError("no se pudo mutar PARAMS")
        open("strategy_multi.py", "w").write(src)
        print(f"[auto {i+1}/{n}] {k} -> {params[k]}", flush=True)
        run(f"auto: {k}={params[k]}")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    if c == "baseline":
        run("baseline")
    elif c == "run":
        run(sys.argv[2] if len(sys.argv) > 2 else "sin descripción")
    elif c == "auto":
        auto(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
