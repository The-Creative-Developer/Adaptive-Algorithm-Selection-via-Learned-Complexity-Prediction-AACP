"""Instance features.

Two groups, following the empirical-hardness-model literature (SATzilla):

* structural (cheap, polynomial, no solver run): size, density, degree
  statistics, clustering, assortativity, degeneracy, a treewidth upper bound,
  spectral quantities of the normalised Laplacian, bipartiteness.
* probing (run a cheap polynomial algorithm and record what it saw): the LP
  relaxation optimum and its half-integral fraction, the greedy-vs-matching
  sandwich gap.

Feature computation time is recorded so the selector can be charged for it.
"""

from __future__ import annotations

import time
import warnings

import networkx as nx
import numpy as np
from networkx.algorithms.approximation import treewidth_min_degree

from .algorithms.flow import nt_half_integral, two_coloring
from .algorithms.greedy import greedy_cover_adj, maximal_matching

STRUCTURAL = [
    "n", "m", "density", "avg_deg", "deg_cv", "max_deg_ratio", "frac_leaves",
    "deg_skew", "clustering", "transitivity", "assortativity", "n_components",
    "giant_frac", "degeneracy", "degeneracy_ratio", "tw_ub", "tw_ratio",
    "lap_gap", "bip_spec", "adj_lambda_ratio", "is_bipartite",
]
PROBING = ["lp_ratio", "lp_half_frac", "lp_one_frac", "sandwich_gap"]
ALL = STRUCTURAL + PROBING


def structural_features(G: nx.Graph) -> dict:
    n = G.number_of_nodes()
    m = G.number_of_edges()
    deg = np.array([d for _, d in G.degree()], dtype=float)
    mean = deg.mean() if n else 0.0
    std = deg.std() if n else 0.0
    f = {
        "n": n,
        "m": m,
        "density": 2 * m / (n * (n - 1)) if n > 1 else 0.0,
        "avg_deg": mean,
        "deg_cv": std / mean if mean > 0 else 0.0,
        "max_deg_ratio": deg.max() / mean if mean > 0 else 0.0,
        "frac_leaves": float(np.mean(deg == 1)),
        "deg_skew": float(((deg - mean) ** 3).mean() / std ** 3) if std > 0 else 0.0,
        "clustering": nx.average_clustering(G),
        "transitivity": nx.transitivity(G),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = nx.degree_assortativity_coefficient(G)
        f["assortativity"] = 0.0 if not np.isfinite(a) else float(a)
    except (ValueError, ZeroDivisionError):
        f["assortativity"] = 0.0
    comps = list(nx.connected_components(G))
    f["n_components"] = len(comps)
    giant = max(comps, key=len)
    f["giant_frac"] = len(giant) / n
    core = nx.core_number(G)
    f["degeneracy"] = max(core.values()) if core else 0
    f["degeneracy_ratio"] = f["degeneracy"] / n
    H = G.subgraph([v for v in G if G.degree(v) > 0])
    tw = treewidth_min_degree(H)[0] if H.number_of_edges() else 0
    f["tw_ub"] = tw
    f["tw_ratio"] = tw / n
    # spectra of the normalised Laplacian of the giant component
    Gg = G.subgraph(giant)
    if Gg.number_of_nodes() > 2:
        Ln = nx.normalized_laplacian_matrix(Gg).toarray()
        ev = np.linalg.eigvalsh(Ln)
        f["lap_gap"] = float(ev[1])            # algebraic connectivity (spectral gap)
        f["bip_spec"] = float(2.0 - ev[-1])    # 0 iff giant component bipartite
        A = nx.to_numpy_array(Gg)
        ea = np.linalg.eigvalsh(A)
        gm = 2 * Gg.number_of_edges() / Gg.number_of_nodes()
        f["adj_lambda_ratio"] = float(ea[-1] / gm) if gm > 0 else 1.0
    else:
        f["lap_gap"], f["bip_spec"], f["adj_lambda_ratio"] = 0.0, 0.0, 1.0
    f["is_bipartite"] = int(two_coloring(G) is not None)
    return f


def probing_features(G: nx.Graph) -> dict:
    n = G.number_of_nodes()
    if G.number_of_edges() == 0:
        return {"lp_ratio": 0.0, "lp_half_frac": 0.0, "lp_one_frac": 0.0,
                "sandwich_gap": 1.0}
    x, lp_val, _ = nt_half_integral(G)
    half = sum(1 for v in x.values() if v == 0.5)
    one = sum(1 for v in x.values() if v == 1.0)
    g = len(greedy_cover_adj({v: set(G[v]) for v in G}))
    M = len(maximal_matching(G))
    return {
        "lp_ratio": lp_val / n,
        "lp_half_frac": half / n,
        "lp_one_frac": one / n,
        # greedy upper bound over the best cheap lower bound
        "sandwich_gap": g / max(M, np.ceil(lp_val), 1),
    }


def compute_features(G: nx.Graph) -> dict:
    t0 = time.perf_counter()
    f = structural_features(G)
    t1 = time.perf_counter()
    f.update(probing_features(G))
    t2 = time.perf_counter()
    f["t_feat_structural"] = t1 - t0
    f["t_feat_probing"] = t2 - t1
    return f
