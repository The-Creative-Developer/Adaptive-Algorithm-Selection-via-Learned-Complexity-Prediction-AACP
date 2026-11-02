"""Shared infrastructure: cooperative deadlines, result records, verification."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Iterable

import networkx as nx


class Timeout(Exception):
    """Raised cooperatively when an algorithm exceeds its time / state budget."""


class Deadline:
    """Cooperative wall-clock deadline (algorithms call :meth:`check`)."""

    def __init__(self, seconds: float | None):
        self.seconds = seconds
        self.t_end = math.inf if seconds is None else time.perf_counter() + seconds

    def remaining(self) -> float:
        return self.t_end - time.perf_counter()

    def check(self) -> None:
        if time.perf_counter() > self.t_end:
            raise Timeout("wall-clock budget exhausted")


@dataclass
class Result:
    """Outcome of one algorithm run.

    cover           -- the vertex cover returned
    proved_optimal  -- the algorithm *certified* optimality (exact search finished,
                       or |cover| matched a valid lower bound)
    ops             -- machine-independent work counter (DP states, search nodes,
                       MIP nodes, augmenting phases ...), used to compare against
                       theoretical bounds without Python-vs-C constant factors
    extra           -- algorithm-specific diagnostics (LP value, width, ...)
    """

    cover: set
    proved_optimal: bool = False
    ops: int = 0
    lower_bound: float = 0.0
    extra: dict = field(default_factory=dict)


def is_vertex_cover(G: nx.Graph, cover: Iterable) -> bool:
    c = set(cover)
    return all(u in c or v in c for u, v in G.edges())


def harmonic(k: int) -> float:
    """H(k) = 1 + 1/2 + ... + 1/k  (greedy set-cover style bound)."""
    return sum(1.0 / i for i in range(1, k + 1))
