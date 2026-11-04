"""Algorithm portfolio for Minimum Vertex Cover.

Every entry has signature ``f(G, deadline) -> Result`` on graphs whose nodes
are the integers 0..n-1.
"""

from .bnb import bnb
from .common import Deadline, Result, Timeout, is_vertex_cover
from .flow import nt_flow
from .greedy import greedy, matching
from .lp import ilp, lp_round
from .td_dp import td_dp

PORTFOLIO = {
    # name       : (function, paradigm, syllabus unit, worst-case guarantee)
    "td_dp":    (td_dp,    "exact DP on tree decomposition", "III", "O(2^tw * tw * n), exact"),
    "bnb":      (bnb,      "backtracking branch & bound",    "IV",  "O*(1.4656^k), exact"),
    "ilp":      (ilp,      "integer LP (HiGHS B&C)",         "VI",  "exponential worst case, exact"),
    "greedy":   (greedy,   "max-degree greedy",              "IV",  "ratio <= H(Delta) = O(log n)"),
    "matching": (matching, "maximal matching (Gavril)",      "IV",  "ratio <= 2"),
    "lp_round": (lp_round, "LP relaxation + rounding",       "VI",  "ratio <= 2"),
    "nt_flow":  (nt_flow,  "König / Nemhauser-Trotter flow", "V",   "exact if bipartite, else ratio <= 2"),
}

EXACT = ["td_dp", "bnb", "ilp"]
APPROX = ["greedy", "matching", "lp_round", "nt_flow"]

__all__ = ["PORTFOLIO", "EXACT", "APPROX", "Deadline", "Result", "Timeout",
           "is_vertex_cover"] + list(PORTFOLIO)
