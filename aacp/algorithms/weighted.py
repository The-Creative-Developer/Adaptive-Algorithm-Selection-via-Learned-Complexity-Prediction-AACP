"""Minimum-*weight* vertex cover versions of the portfolio.

Used for custom problems with vertex costs (``aacp.problems``). Each keeps its
paradigm and its guarantee in the weighted setting:

  td_dp     DP over a tree decomposition with weight sums          exact
  bnb       branch & bound, weighted reductions + local-ratio bound exact
  ilp       weighted objective                                      exact
  greedy    take argmax deg(v)/w(v)  (set-cover greedy)             ratio <= H(Delta)
  matching  Bar-Yehuda-Even local ratio (= Gavril when w = 1)       ratio <= 2
  lp_round  weighted LP, half-integral vertex rounding              ratio <= 2
  nt_flow   weighted König min-cut / weighted Nemhauser-Trotter     exact if bipartite, else <= 2

``solve(name, G, weights, deadline)`` dispatches: with ``weights`` None or all
equal to 1 it runs the original (benchmarked) unit-weight code path.
"""

from __future__ import annotations

import heapq
import math
import sys

import networkx as nx

from .common import Deadline, Result
from .flow import Dinic, two_coloring
from .lp import ilp as _ilp, lp_round as _lp_round
from .td_dp import td_dp as _td_dp

EPS = 1e-9


def cover_weight(cover, weights) -> float:
    return float(sum(weights[v] for v in cover)) if weights is not None else float(len(cover))


# --------------------------------------------------------------- greedy family
def greedy_order_weighted(adj: dict[int, set[int]], w) -> list[int]:
    """Repeatedly take the vertex with the largest deg(v)/w(v); ties -> smallest id."""
    deg = {v: len(nb) for v, nb in adj.items()}
    alive = {v: set(nb) for v, nb in adj.items()}
    key = lambda v: -deg[v] / max(float(w[v]), EPS)
    heap = [(key(v), v) for v in adj if deg[v] > 0]
    heapq.heapify(heap)
    order, taken = [], set()
    while heap:
        k, v = heapq.heappop(heap)
        if v in taken or deg[v] == 0 or abs(k - key(v)) > 1e-12:
            continue
        taken.add(v)
        order.append(v)
        for u in alive[v]:
            alive[u].discard(v)
            deg[u] -= 1
            if deg[u] > 0:
                heapq.heappush(heap, (key(u), u))
        alive[v] = set()
        deg[v] = 0
    return order


def greedy_w(G: nx.Graph, w, deadline: Deadline | None = None) -> Result:
    cover = set(greedy_order_weighted({v: set(G[v]) for v in G}, w))
    return Result(cover=cover, ops=len(cover))


def local_ratio_w(G: nx.Graph, w, deadline: Deadline | None = None) -> Result:
    """Bar-Yehuda & Even: pay min residual on each edge; take vertices paid off.
    The payments are a feasible dual, so their sum is a lower bound on OPT."""
    r = {v: float(w[v]) for v in G}
    paid = 0.0
    for u, v in sorted((min(e), max(e)) for e in G.edges()):
        if r[u] > EPS and r[v] > EPS:
            d = min(r[u], r[v])
            r[u] -= d
            r[v] -= d
            paid += d
    cover = {v for v in G if r[v] <= EPS and G.degree(v) > 0}
    return Result(cover=cover, lower_bound=paid, ops=G.number_of_edges(),
                  proved_optimal=cover_weight(cover, w) <= paid + 1e-7)


# ---------------------------------------------------------------- flow family
def konig_weighted(left, right, edges, w, deadline=None):
    """Minimum-weight vertex cover of a bipartite graph = minimum s-t cut."""
    li = {v: i + 1 for i, v in enumerate(left)}
    ri = {v: i + 1 + len(left) for i, v in enumerate(right)}
    s, t = 0, len(left) + len(right) + 1
    big = sum(float(w[v]) for v in list(left) + list(right)) + 1.0
    D = Dinic(t + 1, eps=1e-9)
    for v in left:
        D.add_edge(s, li[v], float(w[v]))
    for v in right:
        D.add_edge(ri[v], t, float(w[v]))
    for u, v in edges:
        D.add_edge(li[u], ri[v], big)
    f = D.max_flow(s, t, deadline)
    Z = D.reachable(s)
    cover = [v for v in left if li[v] not in Z] + [v for v in right if ri[v] in Z]
    return cover, f, D.phases


def nt_flow_w(G: nx.Graph, w, deadline: Deadline | None = None) -> Result:
    if G.number_of_edges() == 0:
        return Result(cover=set(), proved_optimal=True)
    col = two_coloring(G)
    if col is not None:
        left = [v for v in G if col[v] == 0]
        right = [v for v in G if col[v] == 1]
        edges = [(u, v) if col[u] == 0 else (v, u) for u, v in G.edges()]
        cover, f, phases = konig_weighted(left, right, edges, w, deadline)
        return Result(cover=set(cover), proved_optimal=True, ops=phases, lower_bound=f,
                      extra={"bipartite": True})
    V = list(G)
    wd = {("L", v): w[v] for v in V} | {("R", v): w[v] for v in V}
    E = [(("L", u), ("R", v)) for u, v in G.edges()] + [(("L", v), ("R", u)) for u, v in G.edges()]
    cover, f, phases = konig_weighted([("L", v) for v in V], [("R", v) for v in V], E, wd, deadline)
    cs = set(cover)
    x = {v: ((("L", v) in cs) + (("R", v) in cs)) / 2 for v in V}
    V1 = {v for v, xv in x.items() if xv == 1.0}
    Vh = [v for v, xv in x.items() if xv == 0.5]
    K = G.subgraph(Vh)
    kernel = set(greedy_order_weighted({v: set(K[v]) for v in K}, w))
    cover = V1 | kernel
    lp_val = f / 2.0
    return Result(cover=cover, proved_optimal=cover_weight(cover, w) <= lp_val + 1e-7,
                  ops=phases, lower_bound=lp_val,
                  extra={"bipartite": False, "lp_value": lp_val, "n_half": len(Vh)})


# ------------------------------------------------------------- branch & bound
def bnb_w(G: nx.Graph, w, deadline: Deadline | None = None) -> Result:
    """Weighted B&B. Reductions (each preserves some optimal cover):
       leaf v with neighbour u and w(v) >= w(u): take u;
       degree-2 v in a triangle {v,a,b} with w(v) >= max(w(a), w(b)): take a, b;
       if partial + w(N(v)) >= incumbent, v must be taken (Buss-style).
    Bound: partial + local-ratio dual of the residual graph."""
    deadline = deadline or Deadline(None)
    sys.setrecursionlimit(max(10000, 4 * G.number_of_nodes() + 100))
    W = {v: float(w[v]) for v in G}
    adj0 = {v: set(G[v]) for v in G if G.degree(v) > 0}
    g = greedy_order_weighted(adj0, W)
    best = {"set": set(g), "w": sum(W[v] for v in g)}
    stats = {"nodes": 0, "pruned": 0}

    def remove(adj, v):
        for u in adj.pop(v):
            adj[u].discard(v)

    def dual(adj) -> float:
        r = {v: W[v] for v in adj}
        paid = 0.0
        for u in adj:
            for x in adj[u]:
                if u < x and r[u] > EPS and r[x] > EPS:
                    d = min(r[u], r[x])
                    r[u] -= d; r[x] -= d; paid += d
        return paid

    def solve(adj, partial: list, pw: float):
        stats["nodes"] += 1
        if stats["nodes"] % 128 == 0:
            deadline.check()
        changed = True
        while changed:
            changed = False
            if pw >= best["w"] - 1e-9:
                stats["pruned"] += 1
                return
            for v in list(adj):
                if v not in adj:
                    continue
                d = len(adj[v])
                if d == 0:
                    del adj[v]; changed = True
                elif d == 1:
                    (u,) = adj[v]
                    if W[v] >= W[u]:
                        partial.append(u); pw += W[u]; remove(adj, u); changed = True
                elif d == 2:
                    a, b = adj[v]
                    if b in adj[a] and W[v] >= max(W[a], W[b]):
                        partial.extend((a, b)); pw += W[a] + W[b]
                        remove(adj, a); remove(adj, b); changed = True
                if not changed and v in adj and adj[v] and pw + sum(W[u] for u in adj[v]) >= best["w"] - 1e-9:
                    partial.append(v); pw += W[v]; remove(adj, v); changed = True
                if changed:
                    break
        adj = {v: nb for v, nb in adj.items() if nb}
        if not adj:
            if pw < best["w"] - 1e-9:
                best["set"], best["w"] = set(partial), pw
            return
        if pw + dual(adj) >= best["w"] - 1e-9:
            stats["pruned"] += 1
            return
        v = max(adj, key=lambda x: (len(adj[x]) / max(W[x], EPS), -x))
        a1 = {u: set(nb) for u, nb in adj.items()}
        remove(a1, v)
        solve(a1, partial + [v], pw + W[v])
        a2 = {u: set(nb) for u, nb in adj.items()}
        nbrs = list(a2[v])
        for u in nbrs:
            remove(a2, u)
        a2.pop(v, None)
        solve(a2, partial + nbrs, pw + sum(W[u] for u in nbrs))

    solve({v: set(nb) for v, nb in adj0.items()}, [], 0.0)
    return Result(cover=best["set"], proved_optimal=True, ops=stats["nodes"], extra=dict(stats))


# --------------------------------------------------------------- dispatcher
WEIGHTED = {
    "td_dp": lambda G, w, d: _td_dp(G, d, weights=w),
    "bnb": bnb_w,
    "ilp": lambda G, w, d: _ilp(G, d, weights=w),
    "greedy": greedy_w,
    "matching": local_ratio_w,
    "lp_round": lambda G, w, d: _lp_round(G, d, weights=w),
    "nt_flow": nt_flow_w,
}


def is_unit(weights) -> bool:
    return weights is None or all(math.isclose(float(x), 1.0) for x in
                                  (weights.values() if isinstance(weights, dict) else weights))


def solve(name: str, G: nx.Graph, weights=None, deadline: Deadline | None = None) -> Result:
    from . import PORTFOLIO
    if is_unit(weights):
        return PORTFOLIO[name][0](G, deadline or Deadline(None))
    return WEIGHTED[name](G, weights, deadline or Deadline(None))
