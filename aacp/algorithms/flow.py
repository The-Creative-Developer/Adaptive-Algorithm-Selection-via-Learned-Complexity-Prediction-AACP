"""Unit V -- max-flow (Dinic) based algorithms.

* König's theorem: in a bipartite graph, |max matching| = |min vertex cover|.
  Build the unit network s -> L -> R -> t, run Dinic (O(E sqrt V) on unit
  networks, i.e. Hopcroft-Karp), and read the cover off the min cut:
        C = (L \\ Z) u (R n Z),  Z = vertices reachable from s in the residual.
* Nemhauser-Trotter via flow: for a *general* graph, the optimum of the VC LP
  relaxation equals half the minimum vertex cover of the bipartite double cover
  B(G) (vertices v_L, v_R; edges u_L-v_R and v_L-u_R).  So the Unit-VI LP is
  solved purely combinatorially by a Unit-V max-flow, yielding a half-integral
  optimum x in {0, 1/2, 1}^V.  NT theorem: some optimal cover contains V_1 and
  avoids V_0, so we take V_1 and run greedy on the "kernel" G[V_1/2].  Any cover
  of the kernel has size <= |V_1/2| <= 2 OPT(kernel), so this is a
  2-approximation; it is exact on bipartite graphs (König branch).
"""

from __future__ import annotations

import math
from collections import deque

import networkx as nx

from .common import Deadline, Result
from .greedy import greedy_cover_adj


class Dinic:
    def __init__(self, n: int):
        self.n = n
        self.to: list[int] = []
        self.cap: list[int] = []
        self.head: list[list[int]] = [[] for _ in range(n)]
        self.phases = 0

    def add_edge(self, u: int, v: int, c: int) -> None:
        self.head[u].append(len(self.to)); self.to.append(v); self.cap.append(c)
        self.head[v].append(len(self.to)); self.to.append(u); self.cap.append(0)

    def _bfs(self, s: int, t: int) -> list[int] | None:
        level = [-1] * self.n
        level[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for e in self.head[u]:
                if self.cap[e] > 0 and level[self.to[e]] < 0:
                    level[self.to[e]] = level[u] + 1
                    q.append(self.to[e])
        return level if level[t] >= 0 else None

    def max_flow(self, s: int, t: int, deadline: Deadline | None = None) -> int:
        flow = 0
        while True:
            if deadline:
                deadline.check()
            level = self._bfs(s, t)
            if level is None:
                return flow
            self.phases += 1
            it = [0] * self.n
            # iterative DFS for blocking flow
            while True:
                stack = [s]
                path_edges: list[int] = []
                found = False
                while stack:
                    u = stack[-1]
                    if u == t:
                        found = True
                        break
                    advanced = False
                    while it[u] < len(self.head[u]):
                        e = self.head[u][it[u]]
                        v = self.to[e]
                        if self.cap[e] > 0 and level[v] == level[u] + 1:
                            stack.append(v)
                            path_edges.append(e)
                            advanced = True
                            break
                        it[u] += 1
                    if not advanced:
                        stack.pop()
                        level[u] = -1  # dead end
                        if path_edges:
                            path_edges.pop()
                if not found:
                    break
                push = min(self.cap[e] for e in path_edges)
                for e in path_edges:
                    self.cap[e] -= push
                    self.cap[e ^ 1] += push
                flow += push

    def reachable(self, s: int) -> set[int]:
        seen = {s}
        q = deque([s])
        while q:
            u = q.popleft()
            for e in self.head[u]:
                if self.cap[e] > 0 and self.to[e] not in seen:
                    seen.add(self.to[e])
                    q.append(self.to[e])
        return seen


def two_coloring(G: nx.Graph) -> dict | None:
    color: dict = {}
    for s in G:
        if s in color:
            continue
        color[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for w in G[u]:
                if w not in color:
                    color[w] = 1 - color[u]
                    q.append(w)
                elif color[w] == color[u]:
                    return None
    return color


def konig_cover(left: list, right: list, edges: list[tuple], deadline=None):
    """Min vertex cover of a bipartite graph via max-flow + König.

    Returns (cover, matching_size, phases)."""
    li = {v: i + 1 for i, v in enumerate(left)}
    ri = {v: i + 1 + len(left) for i, v in enumerate(right)}
    s, t = 0, len(left) + len(right) + 1
    D = Dinic(t + 1)
    for v in left:
        D.add_edge(s, li[v], 1)
    for v in right:
        D.add_edge(ri[v], t, 1)
    for u, v in edges:
        D.add_edge(li[u], ri[v], 1)
    f = D.max_flow(s, t, deadline)
    Z = D.reachable(s)
    cover = [v for v in left if li[v] not in Z] + [v for v in right if ri[v] in Z]
    assert len(cover) == f
    return cover, f, D.phases


def nt_half_integral(G: nx.Graph, deadline=None):
    """Optimal half-integral LP solution via the bipartite double cover."""
    V = list(G)
    L = [("L", v) for v in V]
    R = [("R", v) for v in V]
    E = []
    for u, v in G.edges():
        E.append((("L", u), ("R", v)))
        E.append((("L", v), ("R", u)))
    cover, f, phases = konig_cover(L, R, E, deadline)
    cs = set(cover)
    x = {v: ((("L", v) in cs) + (("R", v) in cs)) / 2 for v in V}
    return x, f / 2.0, phases


def nt_flow(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    if G.number_of_edges() == 0:
        return Result(cover=set(), proved_optimal=True)
    col = two_coloring(G)
    if col is not None:
        left = [v for v in G if col[v] == 0]
        right = [v for v in G if col[v] == 1]
        edges = [(u, v) if col[u] == 0 else (v, u) for u, v in G.edges()]
        cover, f, phases = konig_cover(left, right, edges, deadline)
        return Result(cover=set(cover), proved_optimal=True, ops=phases,
                      lower_bound=f, extra={"bipartite": True})
    x, lp_val, phases = nt_half_integral(G, deadline)
    V1 = {v for v, xv in x.items() if xv == 1.0}
    Vh = [v for v, xv in x.items() if xv == 0.5]
    K = G.subgraph(Vh)
    kernel_cover = greedy_cover_adj({v: set(K[v]) for v in K})
    cover = V1 | kernel_cover
    lb = math.ceil(lp_val - 1e-9)
    return Result(cover=cover, proved_optimal=len(cover) == lb, ops=phases,
                  lower_bound=lb,
                  extra={"bipartite": False, "lp_value": lp_val,
                         "n_half": len(Vh), "n_one": len(V1)})
