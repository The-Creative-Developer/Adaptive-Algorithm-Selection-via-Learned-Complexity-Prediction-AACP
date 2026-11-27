"""Evaluate the Problem Studio's live recommendation on fresh custom problems.

68 problems that are not in the benchmark: the 8 demo presets with two new seeds,
each posed as vertex cover and as maximum clique, with unit and with random
integer weights, plus the 4 demo scenarios. For each, run the live analysis,
race all 7 algorithms (3 s budget each) and compare every vote and the
consensus with the actual winner, by accuracy and by PAR10 regret.

    python scripts/evaluate_studio.py [reports/studio_eval.json]
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from aacp import selection as S                      # noqa: E402
from aacp.algorithms import Deadline, Timeout       # noqa: E402
from aacp.algorithms.weighted import solve, cover_weight  # noqa: E402
from aacp.graphs import Spec, make                   # noqa: E402
from aacp.problems import Problem, ProblemError, reduce  # noqa: E402
from aacp.web.live import LiveModel, DEMO_TASKS, RACE_ORDER  # noqa: E402
from aacp.web.scenarios import SCENARIOS             # noqa: E402
from aacp.web.server import PRESETS                  # noqa: E402

BUDGET = 3.0
data = S.load("data")
trees = {t: S.fit_cost_tree(data, t, "structural", depth=3)[0] for t in DEMO_TASKS}
lm = LiveModel(data, trees)
assert lm.wait_ready(300)

problems = []
for p in PRESETS:
    for seed in (11, 12):
        G = make(Spec(p["family"], p["n"], tuple(sorted(p["params"].items())), seed))
        rng = random.Random(seed)
        for kind in ("vertex_cover", "clique"):
            for weighted in (False, True):
                problems.append({"name": f'{p["label"]} s{seed}', "kind": kind, "weighted": weighted,
                                 "body": {"kind": kind, "n": G.number_of_nodes(), "edges": [list(e) for e in G.edges()],
                                          "weights": [rng.randint(1, 10) for _ in G] if weighted else None}})
for sc in SCENARIOS:
    problems.append({"name": sc["title"], "kind": sc["kind"], "weighted": sc["weights"] is not None,
                     "body": {k: sc[k] for k in ("kind", "edges", "weights", "require", "forbid")} | {"n": len(sc["labels"])}})


def winners(results):
    ok = [r for r in results if r["status"] == "ok"]
    pr = [r for r in ok if r["proved"]]
    out = {}
    if pr:
        best = min(r["w"] for r in pr)
        out["certified"] = min((r for r in pr if r["w"] <= best + 1e-9), key=lambda r: r["t"])["alg"]
    if ok:
        target = min(r["w"] for r in pr) if pr else min(r["w"] for r in ok)
        out["optimum"] = min((r for r in ok if r["w"] <= target + 1e-9), key=lambda r: r["t"])["alg"]
    return out


rows = []
t0 = time.time()
for prob in problems:
    try:
        a = lm.analyze(prob["body"], 300)
        r = reduce(Problem.from_json(prob["body"], 300))
    except ProblemError as e:
        print("skip", prob["name"], e)
        continue
    K, w = r.kernel, r.kernel_weights
    res = []
    for alg in RACE_ORDER:
        ts = time.perf_counter()
        try:
            R = solve(alg, K, w, Deadline(BUDGET))
            t = time.perf_counter() - ts
            res.append({"alg": alg, "status": "ok" if t <= BUDGET * 1.05 else "timeout", "t": t,
                        "w": cover_weight(R.cover, w), "proved": bool(R.proved_optimal)})
        except Timeout:
            res.append({"alg": alg, "status": "timeout", "t": BUDGET})
    win = winners(res)
    row = {"name": prob["name"], "kind": prob["kind"], "weighted": prob["weighted"],
           "n": prob["body"]["n"], "kernel_n": K.number_of_nodes(), "kernel_m": K.number_of_edges(),
           "trivial": bool(a.get("trivial")), "winners": win, "res": res}
    if not a.get("trivial"):
        for task in ("certified", "optimum"):
            T = a["tasks"][task]
            votes = {v["source"]: v["choice"] for v in T["consensus"]["votes"]}
            row[task] = {"consensus": T["consensus"]["choice"], "confidence": T["consensus"]["confidence"],
                         **votes, "ood": bool(a["ood"])}
    rows.append(row)
print(f"{len(rows)} problems in {time.time() - t0:.0f}s", flush=True)

PEN = 10 * BUDGET


def cost(row, task, alg):
    """PAR10 time-to-goal of running `alg` on this problem."""
    r = next(x for x in row["res"] if x["alg"] == alg)
    if r["status"] != "ok":
        return PEN
    ok = [x for x in row["res"] if x["status"] == "ok"]
    pr = [x for x in ok if x["proved"]]
    if task == "certified":
        best = min(x["w"] for x in pr)
        return r["t"] if r["proved"] and r["w"] <= best + 1e-9 else PEN
    target = min(x["w"] for x in pr) if pr else min(x["w"] for x in ok)
    return r["t"] if r["w"] <= target + 1e-9 else PEN


summary = {}
for task in ("certified", "optimum"):
    sc = [r for r in rows if not r["trivial"] and task in r["winners"] and task in r]
    def acc(src):
        return sum(r[task].get(src) == r["winners"][task] for r in sc) / len(sc)
    sbs = sum(r["winners"][task] == "bnb" for r in sc) / len(sc)
    hi = [r for r in sc if r[task]["confidence"] >= 0.6]
    lo = [r for r in sc if r[task]["confidence"] < 0.6]
    summary[task] = {
        "n": len(sc), "consensus": acc("consensus"), "tree": acc("tree"), "ehm": acc("ehm"), "knn": acc("knn"),
        "always_bnb": sbs,
        "consensus_unit": sum(r[task]["consensus"] == r["winners"][task] for r in sc if not r["weighted"]) / max(1, sum(not r["weighted"] for r in sc)),
        "consensus_weighted": sum(r[task]["consensus"] == r["winners"][task] for r in sc if r["weighted"]) / max(1, sum(r["weighted"] for r in sc)),
        "hi_conf_n": len(hi), "hi_conf_acc": (sum(r[task]["consensus"] == r["winners"][task] for r in hi) / len(hi)) if hi else None,
        "lo_conf_n": len(lo), "lo_conf_acc": (sum(r[task]["consensus"] == r["winners"][task] for r in lo) / len(lo)) if lo else None,
        "winner_dist": {a: sum(r["winners"][task] == a for r in sc) for a in RACE_ORDER},
        "mean_cost": {src: sum(cost(r, task, r[task].get(src) or "bnb") for r in sc) / len(sc)
                      for src in ("consensus", "tree", "ehm", "knn")},
        "mean_cost_always_bnb": sum(cost(r, task, "bnb") for r in sc) / len(sc),
        "mean_cost_oracle": sum(cost(r, task, r["winners"][task]) for r in sc) / len(sc),
        "failures": {src: sum(cost(r, task, r[task].get(src) or "bnb") >= PEN for r in sc)
                     for src in ("consensus", "tree", "ehm", "knn")} | {"always_bnb": sum(cost(r, task, "bnb") >= PEN for r in sc)},
    }
    m = summary[task]
    m["gap_closed_consensus"] = ((m["mean_cost_always_bnb"] - m["mean_cost"]["consensus"]) /
                                 (m["mean_cost_always_bnb"] - m["mean_cost_oracle"])
                                 if m["mean_cost_always_bnb"] > m["mean_cost_oracle"] else None)
scen = [r for r in rows if not r["name"].endswith(("s11", "s12"))]
out = sys.argv[1] if len(sys.argv) > 1 else "reports/studio_eval.json"
json.dump({"summary": summary, "scenarios": scen, "rows": rows, "trivial": sum(r["trivial"] for r in rows)},
          open(out, "w"), indent=1)
print(json.dumps(summary, indent=1))
for r in scen:
    print(r["name"], r["n"], "->", r["kernel_n"], r["kernel_m"], r["winners"], r.get("certified", {}).get("consensus"))
