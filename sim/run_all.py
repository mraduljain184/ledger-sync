import argparse
import csv
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from server import db
from server.app import app
from sim.backend import ApiBackend
from sim.baselines import SYSTEMS, ModelServer
from sim.simulate import Config, Faults, run_merchant

ORDER = ["S0", "S1", "A1", "A2", "A3", "S2"]


def run_system(name, make_backend, cfg, merchants, seeds):
    rows = []
    for seed in range(seeds):
        backend = make_backend()
        for m in range(merchants):
            res = run_merchant(backend, f"{name}-s{seed}-m{m}", cfg, Faults(), seed * 100_000 + m)
            rows.append({"system": name, "p_conc": cfg.p_conc, "seed": seed, "merchant": m, **res})
    return rows


def summarize(rows):
    print(f"\n{'p_conc':>6} {'sys':>3} {'runs':>4} {'correct%':>8} {'lost':>5} {'dup':>5} "
          f"{'confl/100ev':>11} {'surfaced%':>9} {'inversion%':>10}")
    keys = sorted({(r["p_conc"], r["system"]) for r in rows}, key=lambda k: (k[0], ORDER.index(k[1])))
    for pc, name in keys:
        rs = [r for r in rows if r["p_conc"] == pc and r["system"] == name]
        n = len(rs)
        events = sum(r["events"] for r in rs)
        orc = sum(r["conflicts"] for r in rs)
        flagged = sum(r["conflicts_flagged"] for r in rs)
        based = sum(r["based_edits"] for r in rs)
        print(f"{pc:>6} {name:>3} {n:>4} {100 * sum(r['ok'] for r in rs) / n:>8.1f} "
              f"{sum(r['lost'] for r in rs):>5} {sum(r['dup_rows'] for r in rs):>5} "
              f"{100 * orc / events:>11.2f} {100 * flagged / orc if orc else 0:>9.1f} "
              f"{100 * sum(r['inversions'] for r in rs) / based if based else 0:>10.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merchants", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--levels", default="0.01,0.05,0.2")
    ap.add_argument("--skip-api", action="store_true")
    ap.add_argument("--out", default="results/sync_all.csv")
    a = ap.parse_args()

    rows, t0 = [], time.perf_counter()
    for pc in [float(x) for x in a.levels.split(",")]:
        base = Config(p_conc=pc)
        for name in ORDER[:-1]:
            spec = SYSTEMS[name]
            cfg = replace(base, hybrid=spec["hybrid"])
            rows += run_system(name, lambda s=spec: ModelServer(**s), cfg, a.merchants, a.seeds)
        if not a.skip_api:
            with TestClient(app) as client:
                with db.pool.connection() as conn:
                    conn.execute("TRUNCATE events, batches RESTART IDENTITY")
                rows += run_system("S2", lambda: ApiBackend(client), base, a.merchants, a.seeds)
        print(f"p_conc={pc} done ({time.perf_counter() - t0:.0f}s)")

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summarize(rows)
    print(f"\nsaved to {a.out}")


if __name__ == "__main__":
    main()