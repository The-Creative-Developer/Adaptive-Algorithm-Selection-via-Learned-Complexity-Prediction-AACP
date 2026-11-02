import itertools
import random

import networkx as nx
import pytest

from aacp.algorithms import APPROX, EXACT, PORTFOLIO, Deadline, Timeout, is_vertex_cover
from aacp.algorithms.flow import Dinic, nt_half_integral
from aacp.algorithms.lp import solve_lp
from aacp.graphs import greedy_trap, partial_ktree, make, default_specs


def brute_force(G):
    nodes = list(G)
    for k in range(len(nodes) + 1):
        for S in itertools.combinations(nodes, k):
            if is_vertex_cover(G, S):
                return k


def small_graphs(count=120):
    for s in range(count):
        r = random.Random(s)
        n = r.randint(1, 11)
        kind = s % 4
        if kind == 0:
            G = nx.gnp_random_graph(n, r.random(), seed=s)
        elif kind == 1:
            G = nx.convert_node_labels_to_integers(
                nx.bipartite.random_graph(n // 2 + 1, n - n // 2, r.random(), seed=s))
        elif kind == 2:
            G = partial_ktree(max(n, 4), 3, 0.8, s)
        else:
            G = nx.convert_node_labels_to_integers(nx.cycle_graph(max(n, 3)))
        yield s, G


@pytest.mark.parametrize("name", list(PORTFOLIO))
def test_valid_cover_and_guarantees(name):
    fn = PORTFOLIO[name][0]
    for s, G in small_graphs():
        opt = brute_force(G)
        R = fn(G, Deadline(30))
        assert is_vertex_cover(G, R.cover), (name, s)
        assert R.lower_bound <= opt + 1e-9
        if name in EXACT or R.proved_optimal:
            assert len(R.cover) == opt, (name, s)
        if name in ("matching", "lp_round", "nt_flow"):
            assert len(R.cover) <= 2 * opt


def test_lp_is_half_integral_and_matches_flow():
    for s, G in small_graphs(60):
        if G.number_of_edges() == 0:
            continue
        x = solve_lp(G)
        assert all(min(abs(v), abs(v - 0.5), abs(v - 1)) < 1e-6 for v in x)
        xf, val, _ = nt_half_integral(G)
        assert abs(val - x.sum()) < 1e-6
        assert all(xf[u] + xf[v] >= 1 for u, v in G.edges())


def test_dinic_simple():
    D = Dinic(4)
    D.add_edge(0, 1, 3); D.add_edge(0, 2, 2); D.add_edge(1, 2, 1)
    D.add_edge(1, 3, 2); D.add_edge(2, 3, 3)
    assert D.max_flow(0, 3) == 5


def test_td_dp_width_on_ktree():
    from aacp.algorithms import td_dp
    G = partial_ktree(60, 4, 1.0, 1)
    R = td_dp(G)
    assert R.extra["width"] == 4  # min-fill recovers the k-tree's width exactly
    assert len(R.cover) == len(PORTFOLIO["ilp"][0](G).cover)


def test_td_dp_state_budget():
    from aacp.algorithms import td_dp
    with pytest.raises(Timeout):
        td_dp(nx.complete_graph(30), max_states=1 << 10)


def test_bnb_timeout():
    from aacp.algorithms import bnb
    G = nx.gnp_random_graph(150, 0.2, seed=3)
    with pytest.raises(Timeout):
        bnb(G, Deadline(0.0))


def test_greedy_trap_is_tight():
    from aacp.algorithms import greedy, ilp
    for k in (8, 16):
        G = greedy_trap(k, 0.0, 0)
        g = len(greedy(G).cover)
        assert g == sum(k // i for i in range(2, k + 1))
        assert len(ilp(G).cover) == k


def test_generators_deterministic():
    specs = default_specs(scale=0.2)
    assert len({s.family for s in specs}) == 9
    for sp in specs[::7]:
        G1, G2 = make(sp), make(sp)
        assert sorted(G1.edges()) == sorted(G2.edges())
        assert set(G1.nodes()) == set(range(G1.number_of_nodes()))
