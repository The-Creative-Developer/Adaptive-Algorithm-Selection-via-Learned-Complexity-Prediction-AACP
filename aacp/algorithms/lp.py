"""Unit VI -- integer / linear programming.

ILP:   min sum_v x_v   s.t.  x_u + x_v >= 1  (uv in E),  x in {0,1}^n
LP:    same with 0 <= x <= 1.

* ``ilp``      : exact, solved by HiGHS branch-and-cut (scipy.optimize.milp).
                 ``ops`` = number of B&B nodes; effort is governed by the
                 integrality gap OPT - LP*, not by n.
* ``lp_round`` : solve the LP relaxation with the dual simplex, which returns a
                 basic (vertex) solution.  Vertices of the VC polytope are
                 half-integral (Nemhauser-Trotter), so rounding x_v >= 1/2 gives
                 a 2-approximation; the ratio is at most (|V_1|+|V_1/2|)/OPT and
                 tends to 1 as the half-integral part vanishes.  ceil(LP*) is a
                 lower bound, which can certify optimality.
"""

from __future__ import annotations

import math

import networkx as nx
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csr_matrix

from .common import Deadline, Result, Timeout


def _incidence(G: nx.Graph):
    n = G.number_of_nodes()
    edges = np.array(list(G.edges()), dtype=np.int64).reshape(-1, 2)
    m = len(edges)
    rows = np.repeat(np.arange(m), 2)
    A = csr_matrix((np.ones(2 * m), (rows, edges.ravel())), shape=(m, n))
    return n, m, A


def ilp(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    deadline = deadline or Deadline(None)
    n, m, A = _incidence(G)
    if m == 0:
        return Result(cover=set(), proved_optimal=True)
    tl = deadline.remaining()
    if tl <= 0:
        raise Timeout("no time left")
    opts = {"disp": False}
    if math.isfinite(tl):
        opts["time_limit"] = tl
    res = milp(c=np.ones(n), constraints=LinearConstraint(A, lb=1, ub=np.inf),
               integrality=np.ones(n), bounds=Bounds(0, 1), options=opts)
    if res.status != 0 or res.x is None:
        raise Timeout(f"milp status {res.status}: {res.message}")
    cover = {int(i) for i in np.nonzero(res.x > 0.5)[0]}
    nodes = int(getattr(res, "mip_node_count", 0) or 0)
    return Result(cover=cover, proved_optimal=True, ops=nodes,
                  lower_bound=float(getattr(res, "mip_dual_bound", len(cover))),
                  extra={"mip_nodes": nodes})


def solve_lp(G: nx.Graph) -> np.ndarray:
    n, m, A = _incidence(G)
    if m == 0:
        return np.zeros(n)
    res = linprog(np.ones(n), A_ub=-A, b_ub=-np.ones(m), bounds=(0, 1),
                  method="highs-ds")
    if res.status != 0:
        raise RuntimeError(res.message)
    return res.x


def lp_round(G: nx.Graph, deadline: Deadline | None = None) -> Result:
    x = solve_lp(G)
    cover = {int(i) for i in np.nonzero(x >= 0.5 - 1e-7)[0]}
    lp_val = float(x.sum())
    half = int(np.sum(np.abs(x - 0.5) < 1e-6))
    lb = math.ceil(lp_val - 1e-7)
    return Result(cover=cover, proved_optimal=len(cover) == lb, lower_bound=lb,
                  ops=G.number_of_edges(),
                  extra={"lp_value": lp_val, "n_half": half})
