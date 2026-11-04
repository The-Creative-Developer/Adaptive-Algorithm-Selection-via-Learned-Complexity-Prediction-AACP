import numpy as np
import pandas as pd
import networkx as nx

from aacp.costtree import CostSensitiveTree, CostSensitiveForest
from aacp.features import ALL, compute_features


def test_cost_tree_learns_asymmetric_rule():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 400)
    X = pd.DataFrame({"x": x, "noise": rng.uniform(0, 1, 400)})
    # algorithm a: cheap but catastrophic when x > 0.7 ; b: always moderate
    C = pd.DataFrame({"a": np.where(x > 0.7, 100.0, 0.01), "b": np.full(400, 1.0)})
    t = CostSensitiveTree(max_depth=2).fit(X, C)
    assert abs(t.root_.threshold - 0.7) < 0.05 and t.feature_names_[t.root_.feature] == "x"
    pred = t.predict(X)
    assert (pred[x > 0.72] == "b").all() and (pred[x < 0.68] == "a").all()
    f = CostSensitiveForest(n_estimators=10).fit(X, C)
    assert np.mean(f.predict(X) == np.where(x > 0.7, "b", "a")) > 0.95


def test_features_complete_and_sane():
    G = nx.convert_node_labels_to_integers(nx.complete_bipartite_graph(4, 5))
    f = compute_features(G)
    assert set(ALL) <= set(f)
    assert f["is_bipartite"] == 1 and abs(f["bip_spec"]) < 1e-9
    assert f["clustering"] == 0
    assert abs(f["lp_ratio"] * 9 - 4) < 1e-9  # LP optimum = König number = 4
