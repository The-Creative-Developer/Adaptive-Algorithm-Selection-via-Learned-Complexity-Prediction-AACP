"""Live analysis of custom problems + a cancellable, streaming algorithm race.

``LiveModel.analyze(problem_json)`` answers "which algorithm should solve this?"
with three independent opinions, each trained on the 648-graph benchmark:

  tree   the regret-minimising decision tree (interpretable path + leaf purity)
  ehm    an empirical hardness model: one random forest per algorithm that
         predicts its cost from structural features (SATzilla style)
  knn    the most similar benchmark graphs (z-scored feature space) and which
         algorithm actually won on them

and combines them into a consensus with a confidence score. Every prediction
is made on the *kernel*, i.e. the instance left after reductions, since that is
what the solvers really face.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import Counter

import networkx as nx
import numpy as np
from networkx.algorithms.approximation import treewidth_min_degree
from sklearn.ensemble import RandomForestRegressor

from .. import selection as S
from ..algorithms import EXACT, PORTFOLIO, Deadline, Timeout
from ..algorithms.weighted import cover_weight, solve
from ..features import STRUCTURAL, compute_features
from ..problems import Problem, ProblemError, lift, reduce

DEMO_TASKS = ("certified", "optimum", "budgeted")
RACE_ORDER = ["greedy", "matching", "nt_flow", "lp_round", "bnb", "td_dp", "ilp"]
LOG_FEATURES = {"n", "m", "avg_deg", "tw_ub", "degeneracy", "max_deg_ratio"}
SHOW_PCT = ["n", "m", "density", "avg_deg", "clustering", "assortativity", "deg_cv",
            "tw_ub", "lap_gap", "degeneracy"]
DP_TW_GUARD = 32       # min-degree width above which td_dp cannot fit its 2^23 state budget


def _xform(X: np.ndarray, cols: list[str]) -> np.ndarray:
    X = X.astype(float).copy()
    for j, c in enumerate(cols):
        if c in LOG_FEATURES:
            X[:, j] = np.log1p(np.maximum(X[:, j], 0))
    return X


class LiveModel:
    def __init__(self, data: S.Data, trees: dict):
        self.data, self.trees = data, trees
        inst = data.inst
        self.cols = list(STRUCTURAL)
        self.X = S.feature_matrix(inst, "structural")
        self.instances = list(inst.index)
        Z = _xform(self.X.to_numpy(), self.cols)
        self.mu, self.sd = Z.mean(axis=0), Z.std(axis=0) + 1e-9
        self.Zs = (Z - self.mu) / self.sd
        self.lo, self.hi = self.X.min().to_dict(), self.X.max().to_dict()
        self.sorted_vals = {c: np.sort(self.X[c].to_numpy()) for c in self.cols}
        self.labels = {t: S.labels(data.cost[t], data.times, S.penalty_of(t, data)) for t in DEMO_TASKS}
        self.leaf_stats = {}
        for t, tree in trees.items():
            C = data.cost[t]
            leaves: dict[int, Counter] = {}
            for i in C.index:
                leaf = tree.trace(self.X.loc[i, tree.feature_names_].to_numpy())["leaf"]
                leaves.setdefault(leaf, Counter())[self.labels[t][i]] += 1
            self.leaf_stats[t] = leaves
        self.ehm: dict | None = None
        self.ehm_error: str | None = None
        threading.Thread(target=self._train_ehm, daemon=True).start()

    # ------------------------------------------------------------ training
    def _train_ehm(self):
        try:
            models = {}
            for t in DEMO_TASKS:
                C = self.data.cost[t]
                X = self.X.loc[C.index]
                models[t] = {}
                for a in C.columns:
                    y = C[a].replace(np.inf, 1e3)
                    y = np.log10(y.clip(lower=1e-5)) if t != "budgeted" else y
                    models[t][a] = RandomForestRegressor(
                        n_estimators=120, min_samples_leaf=2, random_state=0, n_jobs=1).fit(X, y)
            self.ehm = models
        except Exception as e:  # pragma: no cover
            self.ehm_error = str(e)

    def wait_ready(self, timeout=120.0) -> bool:
        t0 = time.time()
        while self.ehm is None and self.ehm_error is None and time.time() - t0 < timeout:
            time.sleep(0.05)
        return self.ehm is not None

    # ------------------------------------------------------------- analysis
    def analyze(self, body: dict, max_nodes: int) -> dict:
        t0 = time.perf_counter()
        p = Problem.from_json(body, max_nodes)
        r = reduce(p)
        out = {"reduction": r.summary(), "warnings": []}
        K = r.kernel
        if p.weights is not None:
            w = np.array(p.weights)
            out["weights"] = {"min": float(w.min()), "max": float(w.max()),
                              "cv": float(w.std() / w.mean())}
            if out["weights"]["cv"] > 1e-9:
                out["warnings"].append("Vertex costs vary: the selector was trained on unit-cost graphs, "
                                       "so treat its pick as a structural estimate and let the race decide.")
        if K.number_of_edges() == 0:
            out.update(trivial=True, analysis_ms=1000 * (time.perf_counter() - t0),
                       consensus={"choice": None, "confidence": 1.0, "votes": [],
                                  "message": "Trivial: after reductions no edge is left to decide, "
                                             "so every algorithm answers instantly."})
            return out
        feats = compute_features(K)
        x = np.array([float(feats[c]) for c in self.cols])
        out["features"] = feats
        out["percentiles"] = {c: float(np.searchsorted(self.sorted_vals[c], feats[c], side="right")
                                       / len(self.sorted_vals[c])) for c in SHOW_PCT}
        ood = [c for c in self.cols if feats[c] < self.lo[c] - 1e-9 or feats[c] > self.hi[c] + 1e-9]
        out["ood"] = ood
        if ood:
            out["warnings"].append("Outside the training range on " + ", ".join(ood[:4]) +
                                   (" …" if len(ood) > 4 else "") + ": the model is extrapolating.")
        z = (_xform(x[None, :], self.cols)[0] - self.mu) / self.sd
        dist = np.sqrt(((self.Zs - z) ** 2).sum(axis=1))
        nn = np.argsort(dist)[:7]
        out["tasks"] = {}
        for t in DEMO_TASKS:
            tree = self.trees[t]
            tr = tree.trace(np.array([float(feats[c]) for c in tree.feature_names_]))
            leaf = self.leaf_stats[t].get(tr["leaf"], Counter())
            tot = sum(leaf.values()) or 1
            tr["purity"] = leaf.get(tr["choice"], 0) / tot
            tr["leaf_winners"] = dict(leaf.most_common(4))
            neighbours = []
            for j in nn:
                name = self.instances[j]
                lab = self.labels[t].get(name)
                fam = self.data.inst.at[name, "family"]
                neighbours.append({"instance": name, "family": fam,
                                   "n": int(self.data.inst.at[name, "n"]),
                                   "m": int(self.data.inst.at[name, "m"]),
                                   "winner": None if lab is None or lab == S.UNSOLVED else lab,
                                   "distance": float(dist[j])})
            votes_knn = Counter(nb["winner"] for nb in neighbours[:5] if nb["winner"])
            knn_choice = votes_knn.most_common(1)[0][0] if votes_knn else None
            ehm = None
            if self.ehm is not None:
                X1 = np.array([x])
                import pandas as pd
                Xd = pd.DataFrame(X1, columns=self.cols)
                pred = {a: float(m.predict(Xd)[0]) for a, m in self.ehm[t].items()}
                if t != "budgeted":
                    pred = {a: 10 ** v for a, v in pred.items()}
                ehm = {"pred": pred, "choice": min(pred, key=pred.get)}
            votes = [{"source": "tree", "label": "Regret tree", "choice": tr["choice"]}]
            if ehm:
                votes.append({"source": "ehm", "label": "Runtime model", "choice": ehm["choice"]})
            if knn_choice:
                votes.append({"source": "knn", "label": "Similar graphs", "choice": knn_choice,
                              "support": votes_knn[knn_choice], "of": sum(votes_knn.values())})
            tally = Counter(v["choice"] for v in votes)
            top = max(tally.values())
            leaders = [a for a, c in tally.items() if c == top]
            choice = tr["choice"] if tr["choice"] in leaders else leaders[0]
            agreement = tally[choice] / len(votes)
            confidence = 0.65 * agreement + 0.35 * tr["purity"]
            if ood:
                confidence *= 0.75
            if p.weights is not None and out["weights"]["cv"] > 1e-9:
                confidence *= 0.85
            out["tasks"][t] = {"tree": tr, "ehm": ehm, "neighbours": neighbours,
                               "consensus": {"choice": choice, "confidence": confidence,
                                             "agreement": agreement, "votes": votes}}
        out["ehm_ready"] = self.ehm is not None
        out["analysis_ms"] = 1000 * (time.perf_counter() - t0)
        return out


# ------------------------------------------------------------------ racing
class CancellableDeadline(Deadline):
    def __init__(self, seconds, cancel: threading.Event):
        super().__init__(seconds)
        self.cancel = cancel

    def check(self):
        if self.cancel.is_set():
            raise Timeout("cancelled")
        super().check()


class RaceManager:
    MAX_RUNNING = 2
    TTL = 900

    def __init__(self, max_nodes: int):
        self.max_nodes = max_nodes
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, body: dict) -> dict:
        p = Problem.from_json(body, self.max_nodes)
        r = reduce(p)
        algs = [a for a in RACE_ORDER if a in set(body.get("algorithms") or RACE_ORDER)]
        if not algs:
            raise ProblemError("select at least one algorithm to race")
        budget = float(np.clip(float(body.get("budget", 3.0)), 0.1, 30.0))
        with self.lock:
            now = time.time()
            for k in [k for k, j in self.jobs.items() if now - j["created"] > self.TTL]:
                del self.jobs[k]
            running = sum(1 for j in self.jobs.values() if j["status"] == "running")
            if running >= self.MAX_RUNNING:
                raise ProblemError("two races are already running: wait for one to finish or cancel it")
            jid = uuid.uuid4().hex[:12]
            job = {"id": jid, "status": "running", "created": now, "results": [], "current": None,
                   "algorithms": algs, "budget": budget, "cancel": threading.Event(),
                   "reduction": r.summary(), "best": None}
            self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, r), daemon=True).start()
        return self.public(job)

    def _run(self, job, r):
        K, w = r.kernel, r.kernel_weights
        try:
            tw = treewidth_min_degree(K)[0] if K.number_of_edges() else 0
        except Exception:  # pragma: no cover
            tw = 0
        for a in job["algorithms"]:
            if job["cancel"].is_set():
                break
            job["current"] = a
            row = {"algorithm": a, "exact": a in EXACT}
            if a == "td_dp" and tw > DP_TW_GUARD:
                row.update(status="skipped", time_ms=0.0,
                           reason=f"treewidth bound {tw} > {DP_TW_GUARD}: the 2^tw table cannot fit its budget")
                job["results"].append(row)
                continue
            t0 = time.perf_counter()
            try:
                res = solve(a, K, w, CancellableDeadline(job["budget"], job["cancel"]))
                status = "ok"
            except Timeout as e:
                res, status = None, ("cancelled" if "cancel" in str(e) else "timeout")
            except Exception as e:  # pragma: no cover
                res, status = None, "error"
                row["reason"] = f"{type(e).__name__}: {e}"
            t = time.perf_counter() - t0
            if status == "ok" and t > job["budget"] * 1.05:
                status = "timeout"  # overran inside a non-interruptible library call
            row.update(status=status, time_ms=1000 * t)
            if res is not None and status == "ok":
                L = lift(r, res.cover)
                row.update(L, proved=bool(res.proved_optimal), ops=res.ops,
                           kernel_cover_weight=cover_weight(res.cover, w))
            job["results"].append(row)
        job["current"] = None
        ok = [x for x in job["results"] if x.get("status") == "ok" and x.get("feasible")]
        if ok:
            b = min(ok, key=lambda x: (x["cover_weight"], x["time_ms"]))
            proved = [x for x in ok if x.get("proved")]
            job["best"] = {"algorithm": b["algorithm"], "objective": b["objective"],
                           "cover_weight": b["cover_weight"], "solution": b["solution"],
                           "size": b["size"], "certified": bool(proved) and
                           min(x["cover_weight"] for x in proved) <= b["cover_weight"] + 1e-9}
        job["status"] = "cancelled" if job["cancel"].is_set() else "done"

    def get(self, jid: str) -> dict:
        job = self.jobs.get(jid)
        if job is None:
            raise ProblemError("unknown or expired race")
        return self.public(job)

    def cancel(self, jid: str) -> dict:
        job = self.jobs.get(jid)
        if job is None:
            raise ProblemError("unknown or expired race")
        job["cancel"].set()
        return self.public(job)

    @staticmethod
    def public(job) -> dict:
        return {k: v for k, v in job.items() if k != "cancel"}
