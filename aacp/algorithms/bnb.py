"""Unit IV -- backtracking with branch-and-bound pruning.

Search tree: pick a maximum-degree vertex v and branch on
    (a) v in the cover               -> k decreases by 1
    (b) v not in the cover => N(v) in the cover -> k decreases by deg(v)
After reductions every branching vertex has degree >= 3, giving branching
vector (1, 3) and the classic O*(1.4656^k) bound (k = cover size).

Pruning / reductions applied at every node:
  * degree-0: delete;  degree-1: take the neighbour;
  * degree-2 in a triangle: take both neighbours;
  * Buss high-degree rule: if deg(v) > budget, v must be taken;
  * lower bound: |partial| + |maximal matching of the residual graph|
    (each matching edge needs its own cover vertex); prune if >= incumbent.
The incumbent is initialised with the greedy cover.
"""

from __future__ import annotations

import sys

import networkx as nx

from .common import Deadline, Result
from .greedy import greedy_cover_adj


def _remove(adj: dict[int, set[int]], v: int) -> None:
    for u in adj.pop(v):
        adj[u].discard(v)


def _matching_lb(adj: dict[int, set[int]]) -> int:
    matched: set[int] = set()
    size = 0
    for u in adj:
        if u in matched:
            continue
        for w in adj[u]:
            if w not in matched:
                matched.add(u)
                matched.add(w)
                size += 1
                break
    return size


def bnb(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    deadline = deadline or Deadline(None)
    sys.setrecursionlimit(max(10000, 4 * G.number_of_nodes() + 100))
    adj0 = {v: set(G[v]) for v in G if G.degree(v) > 0}
    best = sorted(greedy_cover_adj(adj0))
    stats = {"nodes": 0, "pruned": 0}

    def solve(adj: dict[int, set[int]], partial: list[int]) -> None:
        nonlocal best
        stats["nodes"] += 1
        if stats["nodes"] % 128 == 0:
            deadline.check()
        # ---- reductions ----
        changed = True
        while changed:
            changed = False
            budget = len(best) - len(partial) - 1  # we need a strictly better cover
            if budget < 0:
                stats["pruned"] += 1
                return
            for v in list(adj):
                if v not in adj:
                    continue
                d = len(adj[v])
                if d == 0:
                    del adj[v]
                    changed = True
                elif d == 1:
                    (u,) = adj[v]
                    partial.append(u)
                    _remove(adj, u)
                    changed = True
                elif d == 2:
                    a, b = adj[v]
                    if b in adj[a]:
                        partial.extend((a, b))
                        _remove(adj, a)
                        _remove(adj, b)
                        changed = True
                elif d > budget:
                    partial.append(v)
                    _remove(adj, v)
                    changed = True
                if changed:
                    break
        adj = {v: nb for v, nb in adj.items() if nb}
        if not adj:
            if len(partial) < len(best):
                best = list(partial)
            return
        if len(partial) + _matching_lb(adj) >= len(best):
            stats["pruned"] += 1
            return
        v = max(adj, key=lambda x: (len(adj[x]), -x))
        # branch (a): take v
        a1 = {u: set(nb) for u, nb in adj.items()}
        _remove(a1, v)
        solve(a1, partial + [v])
        # branch (b): take N(v)
        a2 = {u: set(nb) for u, nb in adj.items()}
        nbrs = list(a2[v])
        for u in nbrs:
            _remove(a2, u)
        a2.pop(v, None)
        solve(a2, partial + nbrs)

    solve({v: set(nb) for v, nb in adj0.items()}, [])
    return Result(cover=set(best), proved_optimal=True, ops=stats["nodes"],
                  extra=dict(stats))
