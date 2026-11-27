import itertools
import random

import networkx as nx
import pytest

from aacp.algorithms import Deadline, is_vertex_cover
from aacp.algorithms.weighted import WEIGHTED, cover_weight, solve
from aacp.problems import Problem, ProblemError, lift, reduce, verify


def brute_weighted_vc(G, w):
    best = float("inf")
    for k in range(G.number_of_nodes() + 1):
        for S in itertools.combinations(G.nodes(), k):
            if is_vertex_cover(G, S):
                best = min(best, sum(w[v] for v in S))
    return best


def brute_problem(p):
    best, sense = None, (1 if p.kind == "vertex_cover" else -1)
    for k in range(p.n + 1):
        for S in itertools.combinations(range(p.n), k):
            if verify(p, S):
                val = sum(p.w(v) for v in S)
                if best is None or sense * val < sense * best:
                    best = val
    return best


@pytest.mark.parametrize("name", list(WEIGHTED))
def test_weighted_algorithms(name):
    for s in range(80):
        r = random.Random(s)
        n = r.randint(1, 9)
        G = nx.gnp_random_graph(n, r.random(), seed=s)
        w = [round(r.uniform(0.5, 9), 2) for _ in range(n)]
        opt = brute_weighted_vc(G, w)
        R = solve(name, G, w, Deadline(10))
        assert is_vertex_cover(G, R.cover)
        cw = cover_weight(R.cover, w)
        assert R.lower_bound <= opt + 1e-6
        if name in ("td_dp", "bnb", "ilp") or R.proved_optimal:
            assert abs(cw - opt) < 1e-6, (name, s)
        if name in ("matching", "lp_round", "nt_flow"):
            assert cw <= 2 * opt + 1e-6


def test_unit_weights_use_benchmarked_path():
    G = nx.petersen_graph()
    for name in WEIGHTED:
        assert len(solve(name, G, [1] * 10).cover) == len(solve(name, G, None).cover)


def test_problem_reductions_against_brute_force():
    for s in range(150):
        r = random.Random(s)
        n = r.randint(2, 8)
        G = nx.gnp_random_graph(n, r.random(), seed=s)
        d = {"kind": r.choice(["vertex_cover", "independent_set", "clique"]), "n": n, "edges": list(G.edges())}
        if r.random() < 0.5:
            d["weights"] = [round(r.uniform(0.5, 5), 1) for _ in range(n)]
        vs = list(range(n)); r.shuffle(vs)
        d["require"], d["forbid"] = vs[:r.randint(0, 2)], vs[2:2 + r.randint(0, 2)]
        p = Problem.from_json(d)
        try:
            red = reduce(p)
        except ProblemError:
            assert brute_problem(p) is None  # only truly infeasible problems are rejected
            continue
        opt = brute_problem(p)
        for name in ("ilp", "bnb", "td_dp"):
            L = lift(red, solve(name, red.kernel, red.kernel_weights).cover)
            assert L["feasible"] and abs(L["objective"] - opt) < 1e-6


def test_clique_matches_networkx():
    G = nx.gnp_random_graph(25, 0.4, seed=7)
    p = Problem.from_json({"kind": "clique", "n": 25, "edges": list(G.edges())})
    red = reduce(p)
    L = lift(red, solve("ilp", red.kernel, None).cover)
    assert L["size"] == max(len(c) for c in nx.find_cliques(G))


def test_validation_messages():
    bad = [({"kind": "x", "n": 2}, "unknown problem kind"),
           ({"kind": "vertex_cover", "n": 2, "edges": [[0, 5]]}, "outside"),
           ({"kind": "vertex_cover", "n": 2, "weights": [1, 0]}, "positive"),
           ({"kind": "vertex_cover", "n": 2, "require": [0], "forbid": [0]}, "both required and forbidden"),
           ({"kind": "vertex_cover", "n": 999}, "at most")]
    for d, msg in bad:
        with pytest.raises(ProblemError, match=msg):
            reduce(Problem.from_json(d))
