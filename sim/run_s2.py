import argparse
import csv
import statistics
import time

from fastapi.testclient import TestClient

from server import db
from server.app import app
from sim.backend import ApiBackend
from sim.simulate import Config, Faults, run_merchant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merchants", type=int, default=20)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--p-conc", type=float, default=0.05)
    ap.add_argument("--out", default="results/sync_s2.csv")
    a = ap.parse_args()

    cfg = Config(p_conc=a.p_conc)
    rows, t0 = [], time.perf_counter()
    with TestClient(app) as client:
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        backend = ApiBackend(client)
        for seed in range(a.seeds):
            for m in range(a.merchants):
                res = run_merchant(backend, f"s{seed}-m{m}", cfg, Faults(), seed * 100_000 + m)
                rows.append({"seed": seed, "merchant": m, "p_conc": a.p_conc, **res})
            print(f"seed {seed} done")

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    ok = sum(r["ok"] for r in rows)
    print(f"\nruns: {len(rows)}   correct: {ok} ({100 * ok / len(rows):.1f}%)")
    print(f"events: {sum(r['events'] for r in rows)}   "
          f"lost: {sum(r['lost'] for r in rows)}   extra: {sum(r['extra'] for r in rows)}")
    print(f"mean conflicts per 100 events: {statistics.mean(r['conflict_rate'] for r in rows):.2f}")
    print(f"faults injected: {sum(r['lost_requests'] for r in rows)} lost requests, "
          f"{sum(r['lost_responses'] for r in rows)} lost responses, "
          f"{sum(r['dup_deliveries'] for r in rows)} duplicates, "
          f"{sum(r['rebatched'] for r in rows)} rebatched")
    print(f"elapsed: {time.perf_counter() - t0:.0f}s   saved to {a.out}")


if __name__ == "__main__":
    main()