"""Unit III -- exact dynamic programming over a tree decomposition.

For a tree decomposition of width w, MVC is solved in O(2^(w+1) * poly(w) * #bags)
time.  For every bag X_t and every subset S of X_t that covers the edges inside
X_t we store

    f_t(S) = min size of a vertex cover of G[V_t] whose intersection with X_t is S,

where V_t is the set of vertices appearing in the subtree rooted at t.  With
children c and separators I_c = X_t & X_c:

    f_t(S) = |S| + sum_c  g_c(S & I_c),
    g_c(R) = min { f_c(S') - |R|  :  S' subset X_c,  S' & I_c = R }.

This is the treewidth analogue of Held-Karp's subset DP: exponential only in
the width, linear in n.  Tables are evaluated with vectorised bitmask
arithmetic (numpy), so the *state count* sum_t 2^|X_t| is the honest
machine-independent cost (reported as ``ops``).

The decomposition is built with the min-fill-in heuristic, so ``w`` is an upper
bound on the true treewidth.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
from networkx.algorithms.approximation import treewidth_min_fill_in

from .common import Deadline, Result, Timeout

# 2^24 float64 states ~ 128 MB worst case.  Larger instances "time out".
MAX_STATES = 1 << 23

_POP8 = np.array([bin(i).count("1") for i in range(256)], dtype=np.int64)


def _popcount(x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(x)
    y = x.copy()
    while np.any(y):
        out += _POP8[y & 0xFF]
        y >>= 8
    return out


def _pack(masks: np.ndarray, positions: list[int]) -> np.ndarray:
    """Extract the bits at ``positions`` of each mask into a compact key."""
    key = np.zeros_like(masks)
    for k, p in enumerate(positions):
        key |= ((masks >> p) & 1) << k
    return key


def td_dp(G: nx.Graph, deadline: Deadline | None = None,
          max_states: int = MAX_STATES) -> Result:
    deadline = deadline or Deadline(None)
    if G.number_of_edges() == 0:
        return Result(cover=set(), proved_optimal=True, extra={"width": 0})

    H = G.subgraph([v for v in G if G.degree(v) > 0]).copy()
    width, T = treewidth_min_fill_in(H)
    states = sum(1 << len(b) for b in T.nodes)
    extra = {"width": width, "bags": T.number_of_nodes(), "states": states}
    if states > max_states:
        raise Timeout(f"state budget: width={width}, states={states}")
    deadline.check()

    bags = list(T.nodes)
    order: list = []          # post-order
    parent: dict = {}
    for comp in nx.connected_components(T):
        root = next(iter(comp))
        parent[root] = None
        stack = [(root, False)]
        while stack:
            t, done = stack.pop()
            if done:
                order.append(t)
                continue
            stack.append((t, True))
            for c in T[t]:
                if c != parent[t]:
                    parent[c] = t
                    stack.append((c, False))
    children = {t: [] for t in bags}
    for t in bags:
        if parent[t] is not None:
            children[parent[t]].append(t)

    verts = {t: sorted(t) for t in bags}
    masks_of = {}
    f_of = {}
    g_of = {}       # projection table of t onto separator with its parent
    childkey_of = {}  # key of t's masks on separator with parent

    for t in order:
        deadline.check()
        vs = verts[t]
        idx = {v: i for i, v in enumerate(vs)}
        b = len(vs)
        masks = np.arange(1 << b, dtype=np.int64)
        f = _popcount(masks).astype(np.float64)
        valid = np.ones(1 << b, dtype=bool)
        for u in vs:
            for w in H[u]:
                if w in idx and idx[u] < idx[w]:
                    i, j = idx[u], idx[w]
                    valid &= (((masks >> i) | (masks >> j)) & 1).astype(bool)
        f[~valid] = np.inf
        for c in children[t]:
            inter = sorted(set(c) & set(t))
            key = _pack(masks, [idx[v] for v in inter])
            f += g_of[c][key]
        masks_of[t] = masks
        f_of[t] = f
        p = parent[t]
        if p is not None:
            inter = sorted(set(t) & set(p))
            key = _pack(masks, [idx[v] for v in inter])
            adj_f = f - _popcount(key)
            g = np.full(1 << len(inter), np.inf)
            np.minimum.at(g, key, adj_f)
            g_of[t] = g
            childkey_of[t] = key

    # ---- traceback (top-down) ----
    cover: set = set()
    chosen: dict = {}
    total = 0.0
    for t in reversed(order):
        p = parent[t]
        f = f_of[t]
        if p is None:
            s = int(np.argmin(f))
            total += f[s]
        else:
            inter = sorted(set(t) & set(p))
            pidx = {v: i for i, v in enumerate(verts[p])}
            want = int(_pack(np.array([chosen[p]], dtype=np.int64),
                             [pidx[v] for v in inter])[0])
            cand = np.nonzero(childkey_of[t] == want)[0]
            s = int(cand[np.argmin(f[cand])])
        chosen[t] = s
        for i, v in enumerate(verts[t]):
            if (s >> i) & 1:
                cover.add(v)
    assert len(cover) == int(total), (len(cover), total)
    return Result(cover=cover, proved_optimal=True, ops=states, extra=extra)
