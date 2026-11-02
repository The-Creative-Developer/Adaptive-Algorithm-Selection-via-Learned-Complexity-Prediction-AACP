"""Unit IV -- greedy heuristics.

* ``greedy``   : repeatedly take a maximum-degree vertex.  No constant factor
                 guarantee: ratio <= H(Delta) = O(log n), and the bound is tight
                 on Johnson-style bipartite "trap" instances (see graphs.py).
* ``matching`` : Gavril's maximal-matching algorithm; take both endpoints of a
                 maximal matching.  Ratio <= 2 because every matching edge needs
                 a distinct cover vertex (|M| <= OPT).
"""

from __future__ import annotations

import heapq

import networkx as nx

from .common import Deadline, Result


def greedy_cover_adj(adj: dict[int, set[int]]) -> set[int]:
    """Max-degree greedy on an adjacency dict (not modified). Ties -> smallest id."""
    deg = {v: len(nb) for v, nb in adj.items()}
    alive = {v: set(nb) for v, nb in adj.items()}
    heap = [(-d, v) for v, d in deg.items() if d > 0]
    heapq.heapify(heap)
    cover: set[int] = set()
    while heap:
        d, v = heapq.heappop(heap)
        if v in cover or -d != deg[v] or deg[v] == 0:
            continue  # stale entry
        cover.add(v)
        for u in alive[v]:
            alive[u].discard(v)
            deg[u] -= 1
            if deg[u] > 0:
                heapq.heappush(heap, (-deg[u], u))
        alive[v] = set()
        deg[v] = 0
    return cover


def greedy(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    adj = {v: set(G[v]) for v in G}
    cover = greedy_cover_adj(adj)
    return Result(cover=cover, ops=len(cover))


def maximal_matching(G: nx.Graph) -> list[tuple[int, int]]:
    matched: set[int] = set()
    M = []
    for u, v in sorted((min(e), max(e)) for e in G.edges()):
        if u not in matched and v not in matched:
            matched.update((u, v))
            M.append((u, v))
    return M


def matching(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    M = maximal_matching(G)
    cover = {x for e in M for x in e}
    # |M| is a valid lower bound; if 2|M| == |M| (only when M empty) it's optimal.
    return Result(cover=cover, ops=G.number_of_edges(), lower_bound=len(M),
                  proved_optimal=len(M) == 0)
