"""Custom problem definitions, solved by exact reduction to (weighted) vertex cover.

Supported problems on a graph G = (V, E) with optional positive vertex weights:

  vertex_cover      min w(C)  s.t. every edge has an endpoint in C
  independent_set   max w(S)  s.t. no edge inside S        S = V \\ C,  C a min cover of G
  clique            max w(K)  s.t. K pairwise adjacent      K = V \\ C,  C a min cover of complement(G)

The two maximisation problems are the textbook NP-completeness reductions run
forwards: S is independent in G  <=>  V \\ S is a vertex cover of G, and K is a
clique of G  <=>  K is independent in the complement. Weights carry over
because w(S) = w(V) - w(C).

Constraints are stated in the user's own terms ("must be in my solution" /
"must not be") and translated into cover constraints, then applied as exact
pre-reductions before any solver runs:

  forced into the cover   -> delete the vertex, pay its weight
  forced out of the cover -> all its neighbours are forced in; delete it

What remains is the *kernel*: the only part an algorithm has to decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

KINDS = {
    "vertex_cover": {
        "label": "Vertex cover", "sense": "min",
        "definition": "Choose the cheapest set of vertices so that every edge has at least one chosen endpoint.",
        "reduction": "Solved directly.",
    },
    "independent_set": {
        "label": "Independent set", "sense": "max",
        "definition": "Choose the most valuable set of vertices with no edge between any two of them.",
        "reduction": "S is independent ⇔ V∖S is a vertex cover, so the best S is V minus a minimum cover.",
    },
    "clique": {
        "label": "Maximum clique", "sense": "max",
        "definition": "Choose the most valuable set of vertices that are all pairwise connected.",
        "reduction": "K is a clique of G ⇔ K is independent in the complement Ḡ ⇔ V∖K covers Ḡ.",
    },
}

MAX_VC_EDGES = 30_000


class ProblemError(ValueError):
    """Invalid or infeasible problem definition (shown to the user verbatim)."""


@dataclass
class Problem:
    kind: str
    n: int
    edges: list[tuple[int, int]]
    weights: list[float] | None = None          # None = unit costs / values
    require: set[int] = field(default_factory=set)  # must be in the solution
    forbid: set[int] = field(default_factory=set)   # must not be in the solution
    labels: list[str] | None = None

    @classmethod
    def from_json(cls, d: dict, max_nodes: int = 300) -> "Problem":
        kind = d.get("kind", "vertex_cover")
        if kind not in KINDS:
            raise ProblemError(f"unknown problem kind {kind!r}")
        n = int(d.get("n", 0))
        if n < 1:
            raise ProblemError("the graph has no vertices")
        if n > max_nodes:
            raise ProblemError(f"{n} vertices: the studio accepts at most {max_nodes}")
        edges = set()
        for e in d.get("edges", []):
            u, v = int(e[0]), int(e[1])
            if not (0 <= u < n and 0 <= v < n):
                raise ProblemError(f"edge ({u}, {v}) refers to a vertex outside 0..{n - 1}")
            if u != v:
                edges.add((min(u, v), max(u, v)))
        weights = d.get("weights")
        if weights is not None:
            if len(weights) != n:
                raise ProblemError("one weight per vertex is required")
            weights = [float(x) for x in weights]
            if any(not (x > 0) or x != x or x == float("inf") for x in weights):
                raise ProblemError("weights must be positive finite numbers")
        require = {int(v) for v in d.get("require", [])}
        forbid = {int(v) for v in d.get("forbid", [])}
        if any(not 0 <= v < n for v in require | forbid):
            raise ProblemError("a constraint refers to a vertex that does not exist")
        both = require & forbid
        if both:
            raise ProblemError(f"vertex {_name(d.get('labels'), min(both))} is both required and forbidden")
        labels = d.get("labels")
        if labels is not None and len(labels) != n:
            labels = None
        return cls(kind, n, sorted(edges), weights, require, forbid, labels)

    def w(self, v: int) -> float:
        return 1.0 if self.weights is None else self.weights[v]

    def graph(self) -> nx.Graph:
        G = nx.Graph()
        G.add_nodes_from(range(self.n))
        G.add_edges_from(self.edges)
        return G


def _name(labels, v) -> str:
    return str(labels[v]) if labels and v < len(labels) else f"v{v}"


@dataclass
class Reduced:
    problem: Problem
    vc_graph: nx.Graph                 # the vertex-cover instance (G or its complement)
    forced_in: set[int]                # cover vertices fixed by constraints
    forced_out: set[int]               # vertices fixed outside the cover
    kernel: nx.Graph                   # relabelled 0..k-1, what the solvers see
    kernel_to_orig: list[int]
    kernel_weights: list[float] | None

    def summary(self) -> dict:
        p = self.problem
        return {
            "kind": p.kind, "label": KINDS[p.kind]["label"], "sense": KINDS[p.kind]["sense"],
            "reduction": KINDS[p.kind]["reduction"], "definition": KINDS[p.kind]["definition"],
            "n": p.n, "m": len(p.edges),
            "vc_n": self.vc_graph.number_of_nodes(), "vc_m": self.vc_graph.number_of_edges(),
            "complemented": p.kind == "clique",
            "forced_in": sorted(self.forced_in), "forced_out": sorted(self.forced_out),
            "kernel_n": self.kernel.number_of_nodes(), "kernel_m": self.kernel.number_of_edges(),
            "weighted": p.weights is not None,
        }


def reduce(p: Problem) -> Reduced:
    G = p.graph()
    if p.kind == "clique":
        H = nx.complement(G)
        if H.number_of_edges() > MAX_VC_EDGES:
            raise ProblemError(
                f"the complement graph has {H.number_of_edges()} edges (limit {MAX_VC_EDGES}); "
                "maximum clique on very sparse graphs is better posed as a smaller instance")
    else:
        H = G
    # translate "in my solution" into cover membership
    if p.kind == "vertex_cover":
        cover_in, cover_out = set(p.require), set(p.forbid)
    else:  # solution = V \ cover
        cover_in, cover_out = set(p.forbid), set(p.require)
    forced_in = set(cover_in)
    for v in cover_out:
        for u in H[v]:
            if u in cover_out:
                a, b = sorted((u, v))
                what = {"vertex_cover": "both forbidden from the cover, but they share an edge",
                        "independent_set": "both required in the set, but they are adjacent",
                        "clique": "both required in the clique, but they are not adjacent"}[p.kind]
                raise ProblemError(f"infeasible: {_name(p.labels, a)} and {_name(p.labels, b)} are {what}")
            forced_in.add(u)
    if forced_in & cover_out:  # cannot happen after the check above, kept as a guard
        raise ProblemError("infeasible constraints")
    fixed = forced_in | cover_out
    keep = [v for v in range(p.n) if v not in fixed]
    K = nx.convert_node_labels_to_integers(H.subgraph(keep), ordering="sorted")
    kw = None if p.weights is None else [p.weights[v] for v in keep]
    return Reduced(p, H, forced_in, set(cover_out), K, keep, kw)


def lift(r: Reduced, kernel_cover) -> dict:
    """Map a kernel cover back to the user's problem and verify it from scratch."""
    p = r.problem
    cover = set(r.forced_in) | {r.kernel_to_orig[v] for v in kernel_cover}
    solution = sorted(cover) if p.kind == "vertex_cover" else sorted(set(range(p.n)) - cover)
    obj = sum(p.w(v) for v in solution)
    return {"solution": solution, "size": len(solution), "objective": obj,
            "cover_weight": sum(p.w(v) for v in cover), "feasible": verify(p, solution)}


def verify(p: Problem, solution) -> bool:
    S = set(solution)
    if S & p.forbid or not p.require <= S:
        return False
    E = set(p.edges)
    if p.kind == "vertex_cover":
        return all(u in S or v in S for u, v in E)
    if p.kind == "independent_set":
        return not any(u in S and v in S for u, v in E)
    s = sorted(S)
    return all((s[i], s[j]) in E for i in range(len(s)) for j in range(i + 1, len(s)))
