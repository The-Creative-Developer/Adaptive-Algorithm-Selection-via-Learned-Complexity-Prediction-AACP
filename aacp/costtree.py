"""Regret-minimising (cost-sensitive) decision trees for algorithm selection.

A standard classification tree minimises *misclassification*, which treats
"ran bnb where greedy would have been 1 ms faster" exactly like "ran greedy where
it is suboptimal and paid the PAR10 penalty".  In algorithm selection the loss is
asymmetric, so we grow the tree on the selection objective itself:

    node cost  = min_a  sum_{i in node} C[i, a]
    split      = argmin over (feature, threshold) of cost(left) + cost(right)

Each leaf predicts the algorithm with the smallest *total* cost on its training
instances.  The tree is as readable as a CART tree, but every leaf is the
regret-optimal constant policy for its region.  Split search is O(F * n * A) per
node via prefix sums over instances sorted by each feature.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class _Node:
    cost: np.ndarray                    # mean cost vector of training instances
    n: int
    feature: int = -1
    threshold: float = 0.0
    left: "_Node | None" = None
    right: "_Node | None" = None

    @property
    def leaf(self) -> bool:
        return self.left is None


class CostSensitiveTree:
    def __init__(self, max_depth=4, min_samples_leaf=5, min_gain=1e-9,
                 max_features=None, random_state=0):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.min_gain = min_gain
        self.max_features = max_features
        self.rng = np.random.default_rng(random_state)

    # ---------------------------------------------------------------- fit
    def fit(self, X: pd.DataFrame, C: pd.DataFrame) -> "CostSensitiveTree":
        self.feature_names_ = list(X.columns)
        self.classes_ = list(C.columns)
        Xv = X.to_numpy(float)
        Cv = np.where(np.isfinite(C.to_numpy(float)), C.to_numpy(float), 1e6)
        self.root_ = self._grow(Xv, Cv, 0)
        return self

    def _grow(self, X, C, depth) -> _Node:
        node = _Node(cost=C.mean(axis=0), n=len(C))
        if depth >= self.max_depth or len(C) < 2 * self.min_samples_leaf:
            return node
        parent = C.sum(axis=0).min()
        best = (parent - self.min_gain, None, None)
        F = X.shape[1]
        feats = np.arange(F)
        if self.max_features:
            k = max(1, int(round(self.max_features * F))) if self.max_features < 1 else int(self.max_features)
            feats = self.rng.choice(F, size=min(k, F), replace=False)
        total = C.sum(axis=0)
        best = self._search(X, C, total, feats, best)
        if best[1] is None and len(feats) < F:   # like sklearn: fall back to remaining features
            rest = np.setdiff1d(np.arange(F), feats)
            best = self._search(X, C, total, rest, best)
        _, f, thr = best
        if f is None:
            return node
        mask = X[:, f] <= thr
        node.feature, node.threshold = int(f), float(thr)
        node.left = self._grow(X[mask], C[mask], depth + 1)
        node.right = self._grow(X[~mask], C[~mask], depth + 1)
        return node

    def _search(self, X, C, total, feats, best):
        L = self.min_samples_leaf
        for f in feats:
            order = np.argsort(X[:, f], kind="stable")
            xs = X[order, f]
            cs = np.cumsum(C[order], axis=0)
            idx = np.arange(L - 1, len(xs) - L)      # split after position i
            if len(idx) == 0:
                continue
            idx = idx[xs[idx] < xs[idx + 1]]         # only between distinct values
            if len(idx) == 0:
                continue
            tot = cs[idx].min(axis=1) + (total - cs[idx]).min(axis=1)
            j = int(np.argmin(tot))
            if tot[j] < best[0]:
                i = idx[j]
                best = (tot[j], int(f), 0.5 * (xs[i] + xs[i + 1]))
        return best

    # ------------------------------------------------------------ predict
    def _leaf(self, x) -> _Node:
        node = self.root_
        while not node.leaf:
            node = node.left if x[node.feature] <= node.threshold else node.right
        return node

    def predict_cost(self, X: pd.DataFrame) -> np.ndarray:
        return np.array([self._leaf(x).cost for x in X.to_numpy(float)])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.array(self.classes_)[self.predict_cost(X).argmin(axis=1)]

    def decision_path(self, x: np.ndarray) -> list[str]:
        node, steps = self.root_, []
        while not node.leaf:
            name = self.feature_names_[node.feature]
            if x[node.feature] <= node.threshold:
                steps.append(f"{name}={x[node.feature]:.3g} <= {node.threshold:.3g}")
                node = node.left
            else:
                steps.append(f"{name}={x[node.feature]:.3g} > {node.threshold:.3g}")
                node = node.right
        return steps

    def export_text(self, fmt="{:.3g}") -> str:
        lines = []

        def rec(node, depth):
            pad = "|   " * depth
            if node.leaf:
                a = int(np.argmin(node.cost))
                lines.append(f"{pad}|--- run {self.classes_[a]}  "
                             f"(n={node.n}, mean cost {fmt.format(node.cost[a])})")
                return
            name = self.feature_names_[node.feature]
            t = fmt.format(node.threshold)
            lines.append(f"{pad}|--- {name} <= {t}")
            rec(node.left, depth + 1)
            lines.append(f"{pad}|--- {name} >  {t}")
            rec(node.right, depth + 1)

        rec(self.root_, 0)
        return "\n".join(lines)

    def feature_usage(self) -> dict:
        """Total cost reduction attributed to each feature (cost-based importance)."""
        imp = dict.fromkeys(self.feature_names_, 0.0)

        def rec(node):
            if node.leaf:
                return
            gain = (node.n * node.cost).min() - ((node.left.n * node.left.cost).min()
                                                 + (node.right.n * node.right.cost).min())
            imp[self.feature_names_[node.feature]] += gain
            rec(node.left); rec(node.right)

        rec(self.root_)
        s = sum(imp.values()) or 1.0
        return {k: v / s for k, v in sorted(imp.items(), key=lambda kv: -kv[1]) if v > 0}


class CostSensitiveForest:
    """Bagged cost-sensitive trees; averages predicted cost vectors."""

    def __init__(self, n_estimators=100, max_depth=6, min_samples_leaf=3,
                 max_features=0.5, random_state=0):
        self.kw = dict(max_depth=max_depth, min_samples_leaf=min_samples_leaf,
                       max_features=max_features)
        self.n_estimators = n_estimators
        self.random_state = random_state

    def fit(self, X: pd.DataFrame, C: pd.DataFrame):
        rng = np.random.default_rng(self.random_state)
        self.classes_ = list(C.columns)
        self.trees_ = []
        n = len(X)
        for b in range(self.n_estimators):
            idx = rng.integers(0, n, n)
            t = CostSensitiveTree(random_state=int(rng.integers(1 << 31)), **self.kw)
            self.trees_.append(t.fit(X.iloc[idx], C.iloc[idx]))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        cost = np.mean([t.predict_cost(X) for t in self.trees_], axis=0)
        return np.array(self.classes_)[cost.argmin(axis=1)]
