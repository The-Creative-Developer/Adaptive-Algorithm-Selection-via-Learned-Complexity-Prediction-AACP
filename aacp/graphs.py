"""Instance generators with *controlled structure*.

Each family deliberately moves one structural knob, so that we can see where an
algorithm's empirical behaviour departs from its worst-case bound:

  family            knob(s) being varied                      relevant theory
  ----------------  ----------------------------------------  ---------------------------
  er                density p (sparse -> dense)                matching ratio, LP gap
  ba                degree heterogeneity (power-law tail)      greedy, Buss rule
  ws                clustering via rewiring beta               greedy vs clustering
  plc               clustering at fixed power-law degrees      greedy vs clustering
  rgg               geometric locality (high clustering, tw)   DP vs tw
  ktree             treewidth exactly <= k                     DP O(2^tw n)
  bipartite         bipartiteness (König applies)              flow exact, LP integral
  sbm               community structure (network segments)     B&B, ILP
  trap              Johnson-style greedy lower-bound gadget    greedy ratio -> H(k)

All generators return graphs on nodes 0..n-1 with a *random relabelling* so
that index-based tie-breaking cannot exploit construction order.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict

import networkx as nx


@dataclass(frozen=True)
class Spec:
    family: str
    n: int
    params: tuple  # tuple of (key, value) pairs
    seed: int

    @property
    def name(self) -> str:
        ps = "_".join(f"{k}{v}" for k, v in self.params)
        return f"{self.family}_n{self.n}_{ps}_s{self.seed}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["params"] = dict(self.params)
        return d


def _relabel(G: nx.Graph, seed: int) -> nx.Graph:
    G = nx.Graph(G)
    G.remove_edges_from(nx.selfloop_edges(G))
    nodes = list(G.nodes())
    perm = list(range(len(nodes)))
    random.Random(seed ^ 0x5EED).shuffle(perm)
    H = nx.Graph()
    H.add_nodes_from(range(len(nodes)))
    m = {v: perm[i] for i, v in enumerate(nodes)}
    H.add_edges_from((m[u], m[v]) for u, v in G.edges())
    return H


def partial_ktree(n: int, k: int, keep: float, seed: int) -> nx.Graph:
    """Random k-tree on n vertices, then keep each edge with prob ``keep``.
    Treewidth <= k by construction (exactly k before edge deletion)."""
    rng = random.Random(seed)
    G = nx.complete_graph(k + 1)
    cliques = [tuple(range(k + 1))]
    for v in range(k + 1, n):
        base = rng.choice(cliques)
        drop = rng.randrange(k + 1)
        clique = tuple(x for i, x in enumerate(base) if i != drop)
        G.add_edges_from((v, u) for u in clique)
        cliques.append(clique + (v,))
    H = nx.Graph()
    H.add_nodes_from(G)
    H.add_edges_from(e for e in G.edges() if rng.random() < keep)
    return H


def greedy_trap(k: int, noise: float, seed: int) -> nx.Graph:
    """Johnson's construction: L = k vertices; for i = 2..k, block R_i has
    floor(k/i) vertices, each adjacent to a distinct group of i L-vertices.
    Every L-vertex has degree <= i-1 once R_k..R_{i+1} are gone, while R_i
    vertices have degree i, so max-degree greedy takes all of R:
    sum_{i>=2} floor(k/i) ~ k (H(k) - 1) vertices, whereas OPT <= |L| = k.  ``noise`` adds random
    L-R edges to see how robust the trap is."""
    rng = random.Random(seed)
    G = nx.Graph()
    L = list(range(k))
    G.add_nodes_from(L)
    nxt = k
    R = []
    for i in range(2, k + 1):
        for g in range(k // i):
            G.add_edges_from((nxt, L[g * i + j]) for j in range(i))
            R.append(nxt)
            nxt += 1
    for r in R:
        for l in L:
            if rng.random() < noise:
                G.add_edge(r, l)
    return G


def make(spec: Spec) -> nx.Graph:
    p = dict(spec.params)
    n, s = spec.n, spec.seed
    f = spec.family
    if f == "er":
        G = nx.gnp_random_graph(n, p["p"], seed=s)
    elif f == "ba":
        G = nx.barabasi_albert_graph(n, p["m"], seed=s)
    elif f == "ws":
        G = nx.connected_watts_strogatz_graph(n, p["k"], p["beta"], seed=s)
    elif f == "plc":
        G = nx.powerlaw_cluster_graph(n, p["m"], p["pt"], seed=s)
    elif f == "rgg":
        G = nx.random_geometric_graph(n, p["r"], seed=s)
    elif f == "ktree":
        G = partial_ktree(n, p["k"], p["keep"], s)
    elif f == "bipartite":
        n1 = int(n * p["frac"])
        G = nx.bipartite.random_graph(n1, n - n1, p["p"], seed=s)
    elif f == "sbm":
        b = p["blocks"]
        sizes = [n // b + (1 if i < n % b else 0) for i in range(b)]
        P = [[p["pin"] if i == j else p["pout"] for j in range(b)] for i in range(b)]
        G = nx.stochastic_block_model(sizes, P, seed=s)
    elif f == "trap":
        G = greedy_trap(p["k"], p["noise"], s)
    else:
        raise ValueError(f)
    return _relabel(G, s)


def default_specs(scale: float = 1.0, seed: int = 0, n_range=(30, 200)) -> list[Spec]:
    """The benchmark suite.  ``scale`` multiplies the number of seeds."""
    rng = random.Random(seed)
    reps = max(1, round(6 * scale))
    grid: list[tuple[str, dict]] = []
    for p in (0.03, 0.06, 0.1, 0.2, 0.35, 0.6):
        grid.append(("er", {"p": p}))
    for m in (1, 2, 3, 5):
        grid.append(("ba", {"m": m}))
    for k in (4, 6):
        for beta in (0.0, 0.1, 0.3, 1.0):
            grid.append(("ws", {"k": k, "beta": beta}))
    for m in (2, 4):
        for pt in (0.0, 0.5, 0.9):
            grid.append(("plc", {"m": m, "pt": pt}))
    for r in (0.12, 0.2, 0.3):
        grid.append(("rgg", {"r": r}))
    for k in (2, 4, 7, 10, 14):
        for keep in (0.7, 1.0):
            grid.append(("ktree", {"k": k, "keep": keep}))
    for p in (0.05, 0.15, 0.4):
        for frac in (0.3, 0.5):
            grid.append(("bipartite", {"p": p, "frac": frac}))
    for blocks, pin, pout in ((3, 0.3, 0.02), (5, 0.5, 0.01), (4, 0.15, 0.05)):
        grid.append(("sbm", {"blocks": blocks, "pin": pin, "pout": pout}))
    specs = []
    for fam, params in grid:
        for r in range(reps):
            sd = rng.randrange(1 << 30)
            n = rng.randint(*n_range)
            if fam == "trap":
                continue
            specs.append(Spec(fam, n, tuple(sorted(params.items())), sd))
    for k in (8, 12, 16, 24, 32, 40):
        for noise in (0.0, 0.01, 0.03, 0.08):
            for r in range(max(1, reps // 3)):
                sd = rng.randrange(1 << 30)
                G_n = greedy_trap(k, 0.0, 0).number_of_nodes()
                specs.append(Spec("trap", G_n, (("k", k), ("noise", noise)), sd))
    return specs
