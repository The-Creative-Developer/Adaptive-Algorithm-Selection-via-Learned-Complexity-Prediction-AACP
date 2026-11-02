"""Run the portfolio on every instance and record time / quality / work.

Outputs (in ``outdir``):
  instances.csv  -- one row per instance: spec + features + reference optimum
  runs.csv       -- one row per (instance, algorithm)
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import multiprocessing as mp
import time
import traceback
from pathlib import Path

import pandas as pd

from .algorithms import PORTFOLIO, Deadline, Timeout, is_vertex_cover
from .algorithms.lp import ilp
from .features import compute_features
from .graphs import Spec, default_specs, make

FAST = 0.05      # runs faster than this are repeated and the minimum is kept
REPEATS = 3


def _timed(fn, G, budget):
    t0 = time.perf_counter()
    try:
        R = fn(G, Deadline(budget))
        status = "ok"
    except Timeout as e:
        R, status = None, "timeout"
        msg = str(e)
    t = time.perf_counter() - t0
    if status == "ok" and t > budget:  # non-cooperative overrun (e.g. inside a library call)
        status = "timeout"
    return R, status, t


def run_instance(spec: Spec, budget: float, ref_budget: float) -> tuple[dict, list[dict]]:
    G = make(spec)
    inst = {"instance": spec.name, "family": spec.family, "seed": spec.seed,
            "params": json.dumps(dict(spec.params))}
    inst.update(compute_features(G))
    runs = []
    for name, (fn, *_r) in PORTFOLIO.items():
        R, status, t = _timed(fn, G, budget)
        if status == "ok" and t < FAST:
            for _ in range(REPEATS - 1):
                _, _, t2 = _timed(fn, G, budget)
                t = min(t, t2)
        row = {"instance": spec.name, "algorithm": name, "status": status, "time": t}
        if R is not None:
            assert is_vertex_cover(G, R.cover), (spec.name, name)
            row.update(size=len(R.cover), proved=bool(R.proved_optimal), ops=R.ops,
                       lower_bound=R.lower_bound)
            for k, v in R.extra.items():
                if isinstance(v, (int, float, bool)):
                    row[f"x_{k}"] = v
        else:
            row.update(size=None, proved=False, ops=None, lower_bound=None)
        runs.append(row)

    proved = {r["size"] for r in runs if r["status"] == "ok" and r["proved"]}
    assert len(proved) <= 1, (spec.name, runs)
    if proved:
        opt, src = proved.pop(), "portfolio"
    else:
        try:
            opt, src = len(ilp(G, Deadline(ref_budget)).cover), "ilp_ref"
        except Timeout:
            sizes = [r["size"] for r in runs if r["size"] is not None]
            opt, src = (min(sizes) if sizes else None), "best_known"
    inst["opt"] = opt
    inst["opt_source"] = src
    return inst, runs


def _worker(args):
    spec, budget, ref_budget = args
    try:
        return run_instance(spec, budget, ref_budget)
    except Exception:  # pragma: no cover
        return {"instance": spec.name, "error": traceback.format_exc()}, []


def run(specs, outdir: Path, budget: float, ref_budget: float, jobs: int) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    insts, runs = [], []
    t0 = time.time()
    with mp.get_context("fork").Pool(jobs, maxtasksperchild=20) as pool:
        it = pool.imap_unordered(_worker, [(s, budget, ref_budget) for s in specs])
        for i, (inst, rs) in enumerate(it, 1):
            if "error" in inst:
                print("ERROR", inst["instance"], inst["error"], flush=True)
                continue
            insts.append(inst)
            runs.extend(rs)
            if i % 25 == 0 or i == len(specs):
                print(f"[{i}/{len(specs)}] {time.time() - t0:.0f}s", flush=True)
    order = {s.name: i for i, s in enumerate(specs)}
    I = pd.DataFrame(insts).sort_values("instance", key=lambda c: c.map(order))
    R = pd.DataFrame(runs).sort_values(["instance", "algorithm"],
                                       key=lambda c: c.map(order) if c.name == "instance" else c)
    I.to_csv(outdir / "instances.csv", index=False)
    R.to_csv(outdir / "runs.csv", index=False)
    meta = {"budget": budget, "ref_budget": ref_budget, "jobs": jobs,
            "n_instances": len(I), "wall_seconds": time.time() - t0}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--scale", type=float, default=2.0, help="seeds multiplier")
    ap.add_argument("--budget", type=float, default=5.0, help="seconds per algorithm run")
    ap.add_argument("--ref-budget", type=float, default=60.0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    specs = default_specs(scale=a.scale, seed=a.seed)
    if a.limit:
        specs = specs[:: max(1, len(specs) // a.limit)][: a.limit]
    run(specs, a.out, a.budget, a.ref_budget, a.jobs)


if __name__ == "__main__":
    main()
