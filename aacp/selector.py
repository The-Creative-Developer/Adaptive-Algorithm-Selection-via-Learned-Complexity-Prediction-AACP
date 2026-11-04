"""Deployable selector: structural features -> regret-minimising tree -> run the
chosen algorithm, with a human-readable explanation of the decision."""

from __future__ import annotations

import networkx as nx
import numpy as np

from . import selection as S
from .algorithms import PORTFOLIO, Deadline
from .features import structural_features


class AlgorithmSelector:
    def __init__(self, tree, task):
        self.tree, self.task = tree, task

    @classmethod
    def train(cls, datadir="data", task="certified", depth=4):
        tree, _ = S.fit_cost_tree(S.load(datadir), task, "structural", depth=depth)
        return cls(tree, task)

    def _x(self, G):
        f = structural_features(G)
        return np.array([float(f[c]) for c in self.tree.feature_names_])

    def choose(self, G: nx.Graph) -> str:
        import pandas as pd
        x = self._x(G)
        return str(self.tree.predict(pd.DataFrame([x], columns=self.tree.feature_names_))[0])

    def explain(self, G: nx.Graph) -> tuple[str, str]:
        return self.choose(G), " AND ".join(self.tree.decision_path(self._x(G))) or "(root)"

    def solve(self, G: nx.Graph, budget: float | None = None):
        return PORTFOLIO[self.choose(G)][0](G, Deadline(budget))
