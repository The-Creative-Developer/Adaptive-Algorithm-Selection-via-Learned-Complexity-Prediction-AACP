"""Learned algorithm selection.

Three selection tasks are derived from the benchmark:

  certified -- minimise time until a *certified* optimum (PAR10; uncertified or
               timed-out runs cost 10 x budget).  The classic exact-solver
               selection problem.
  optimum   -- minimise time until the returned cover *is* optimal, certified or
               not (PAR10).  Here a cheap heuristic that happens to hit OPT wins;
               it answers "when is a heuristic already enough?".
  budgeted  -- real-time setting: every algorithm gets a hard budget TAU (50 ms);
               cost = |C|/OPT if it finished within TAU, else BUDGET_PENALTY.
               Exact solvers and heuristics compete directly on quality.
  approx    -- among the polynomial algorithms only, minimise the approximation
               ratio |C|/OPT (label ties broken by time; cost is the ratio).

Selectors:
  tree        -- depth-limited CART classifier on the oracle label (accuracy objective)
  forest      -- random forest classifier on the oracle label
  cost_tree   -- regret-minimising decision tree (see costtree.py); interpretable
  cost_forest -- bagged regret-minimising trees
  ehm    -- empirical hardness model: one random-forest *regressor* per
            algorithm predicting log10(cost); choose the argmin (SATzilla style)

Evaluation: stratified 5-fold CV and leave-one-family-out (LOFO); the single
best solver (SBS) is always chosen on the training folds only.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.tree import DecisionTreeClassifier

from .algorithms import APPROX, PORTFOLIO
from .costtree import CostSensitiveForest, CostSensitiveTree
from .features import PROBING, STRUCTURAL

ALGS = list(PORTFOLIO)
TASKS = ("certified", "optimum", "budgeted", "approx")
TAU = 0.05            # seconds, budgeted task
BUDGET_PENALTY = 3.0  # worse than any ratio observed for an in-budget run
N_JOBS = int(os.environ.get("AACP_JOBS", "-1"))
MODELS = ("tree", "forest", "cost_tree", "cost_forest", "ehm")


@dataclass
class Data:
    inst: pd.DataFrame       # indexed by instance
    cost: dict               # task -> DataFrame (instance x algorithm)
    budget: float
    times: pd.DataFrame = None  # raw wall-clock times (instance x algorithm)


def load(datadir) -> Data:
    import json
    from pathlib import Path
    datadir = Path(datadir)
    inst = pd.read_csv(datadir / "instances.csv").set_index("instance")
    runs = pd.read_csv(datadir / "runs.csv")
    budget = json.loads((datadir / "meta.json").read_text())["budget"]
    P = 10 * budget
    runs = runs.join(inst[["opt", "opt_source"]], on="instance")
    ok = runs["status"].eq("ok")
    t = runs.set_index(["instance", "algorithm"])
    cert = np.where(ok & runs["proved"].astype(bool), runs["time"], P)
    hit = np.where(ok & (runs["size"] == runs["opt"]), runs["time"], P)
    ratio = (runs["size"] / runs["opt"]).where(ok, np.inf)
    cost = {
        "certified": pd.Series(cert, index=t.index).unstack()[ALGS],
        "optimum": pd.Series(hit, index=t.index).unstack()[ALGS],
        "budgeted": pd.Series(np.where(ok & (runs["time"] <= TAU), ratio, BUDGET_PENALTY),
                              index=t.index).unstack()[ALGS],
        "approx": pd.Series(ratio.values, index=t.index).unstack()[APPROX],
    }
    times = pd.Series(runs["time"].values, index=t.index).unstack()
    known = inst["opt_source"].isin(["portfolio", "ilp_ref"])
    for k in ("optimum", "budgeted", "approx"):
        cost[k] = cost[k].loc[known[known].index]
    return Data(inst=inst, cost=cost, budget=budget, times=times)


def labels(C: pd.DataFrame, times: pd.DataFrame | None = None) -> pd.Series:
    """Oracle label = argmin cost; exact ties (common for ratios) go to the faster one."""
    if times is None:
        return C.idxmin(axis=1)
    T = times.loc[C.index, C.columns]
    best = C.min(axis=1)
    tied = C.le(best + 1e-12, axis=0)
    return T.where(tied).idxmin(axis=1)


def feature_matrix(inst: pd.DataFrame, featureset: str) -> pd.DataFrame:
    cols = STRUCTURAL if featureset == "structural" else STRUCTURAL + PROBING
    return inst[cols].astype(float).fillna(0.0)


def feature_time(inst: pd.DataFrame, featureset: str) -> pd.Series:
    t = inst["t_feat_structural"]
    return t + inst["t_feat_probing"] if featureset != "structural" else t


def make_model(kind: str, seed: int = 0):
    if kind == "tree":
        return DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=seed)
    if kind == "forest":
        return RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                      random_state=seed, n_jobs=N_JOBS)
    raise ValueError(kind)


def train_costs(C: pd.DataFrame, T: pd.DataFrame | None) -> pd.DataFrame:
    """Training-time cost matrix: add a negligible time term so that exact quality
    ties (frequent for ratios) are resolved in favour of the faster algorithm."""
    if T is None:
        return C
    return C + 1e-4 * T.loc[C.index, C.columns].fillna(0)


def _fit_predict(kind, Xtr, Ctr, Xte, seed=0, Ttr=None):
    if kind in ("cost_tree", "cost_forest"):
        m = (CostSensitiveTree(max_depth=4, min_samples_leaf=5, random_state=seed)
             if kind == "cost_tree" else CostSensitiveForest(random_state=seed))
        m.fit(Xtr, train_costs(Ctr, Ttr))
        return pd.Series(m.predict(Xte), index=Xte.index)
    if kind == "ehm":
        preds = {}
        for a in Ctr.columns:
            y = np.log10(Ctr[a].replace(np.inf, 1e3).clip(lower=1e-5))
            if Ttr is not None:  # tiny time term so ties in quality resolve to the faster one
                y = y + 1e-4 * np.log10(Ttr.loc[Ctr.index, a].clip(lower=1e-6))
            r = RandomForestRegressor(n_estimators=200, min_samples_leaf=2,
                                      random_state=seed, n_jobs=N_JOBS).fit(Xtr, y)
            preds[a] = r.predict(Xte)
        return pd.DataFrame(preds, index=Xte.index).idxmin(axis=1)
    ytr = labels(Ctr, Ttr)
    m = make_model(kind, seed).fit(Xtr, ytr)
    return pd.Series(m.predict(Xte), index=Xte.index)


def _splits(protocol, X, y, groups, seed):
    if protocol == "cv":
        vc = y.value_counts()
        strat = y.where(y.map(vc) >= 5, "_rare")  # avoid tiny classes breaking stratification
        return StratifiedKFold(5, shuffle=True, random_state=seed).split(X, strat)
    return GroupKFold(n_splits=groups.nunique()).split(X, y, groups)


def evaluate(data: Data, task: str, kind: str, featureset: str, protocol: str,
             seed: int = 0) -> tuple[dict, pd.DataFrame]:
    C = data.cost[task]
    inst = data.inst.loc[C.index]
    X = feature_matrix(inst, featureset)
    y = labels(C, data.times)
    groups = inst["family"]
    chosen = pd.Series(index=C.index, dtype=object)
    sbs = pd.Series(index=C.index, dtype=object)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for tr, te in _splits(protocol, X, y, groups, seed):
            itr, ite = C.index[tr], C.index[te]
            chosen.loc[ite] = _fit_predict(kind, X.loc[itr], C.loc[itr], X.loc[ite], seed,
                                           data.times).values
            Ctr = C.loc[itr]
            s = (Ctr.replace(np.inf, 1e3).mean()).idxmin()
            sbs.loc[ite] = s
    pick = lambda sel: np.array([C.at[i, a] for i, a in sel.items()])
    as_c, sbs_c, vbs_c = pick(chosen), pick(sbs), C.min(axis=1).values
    ftime = feature_time(inst, featureset).values
    res = {
        "task": task, "model": kind, "features": featureset, "protocol": protocol,
        "n": len(C), "accuracy": float(np.mean(chosen.values == y.values)),
    }
    if task in ("approx", "budgeted"):
        res.update(AS=float(np.mean(as_c)), SBS=float(np.mean(sbs_c)),
                   VBS=float(np.mean(vbs_c)))
    else:
        P = 10 * data.budget
        res.update(AS=float(np.mean(as_c)), AS_feat=float(np.mean(as_c + ftime)),
                   SBS=float(np.mean(sbs_c)), VBS=float(np.mean(vbs_c)),
                   solved_AS=float(np.mean(as_c < P)), solved_SBS=float(np.mean(sbs_c < P)))
    denom = res["SBS"] - res["VBS"]
    res["gap_closed"] = float((res["SBS"] - res["AS"]) / denom) if denom > 1e-9 else float("nan")
    detail = pd.DataFrame({"label": y, "chosen": chosen, "sbs": sbs,
                           "cost_AS": as_c, "cost_SBS": sbs_c, "cost_VBS": vbs_c,
                           "family": groups})
    return res, detail


def evaluate_all(data: Data, seed: int = 0) -> pd.DataFrame:
    rows = []
    for task in TASKS:
        for protocol in ("cv", "lofo"):
            for fs in ("structural", "all"):
                for kind in MODELS:
                    r, _ = evaluate(data, task, kind, fs, protocol, seed)
                    rows.append(r)
    return pd.DataFrame(rows)


def fit_interpretable(data: Data, task: str, featureset: str = "structural",
                      depth: int = 3):
    """Accuracy-objective CART tree (for comparison with the cost tree)."""
    C = data.cost[task]
    X = feature_matrix(data.inst.loc[C.index], featureset)
    y = labels(C, data.times)
    m = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=5, random_state=0).fit(X, y)
    return m, X, y


def fit_cost_tree(data: Data, task: str, featureset: str = "structural", depth: int = 3):
    C = data.cost[task]
    X = feature_matrix(data.inst.loc[C.index], featureset)
    m = CostSensitiveTree(max_depth=depth, min_samples_leaf=5).fit(X, train_costs(C, data.times))
    return m, X


def importances(data: Data, task: str, featureset: str = "all", seed: int = 0) -> pd.DataFrame:
    """Gini importance (forest) and permutation importance on a held-out split."""
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import train_test_split
    C = data.cost[task]
    X = feature_matrix(data.inst.loc[C.index], featureset)
    y = labels(C, data.times)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=seed)
    m = make_model("forest", seed).fit(Xtr, ytr)
    pi = permutation_importance(m, Xte, yte, n_repeats=20, random_state=seed, n_jobs=N_JOBS)
    return pd.DataFrame({"gini": m.feature_importances_, "perm_mean": pi.importances_mean,
                         "perm_std": pi.importances_std}, index=X.columns
                        ).sort_values("perm_mean", ascending=False)
