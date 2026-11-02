"""Command line entry point.

    python -m aacp benchmark [--scale 2 --budget 5]   # run portfolio -> data/
    python -m aacp analyze   [--data data --out reports]
    python -m aacp select    --graph edges.txt        # pick an algorithm for a new graph
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "benchmark":
        from .benchmark import main as bm
        bm(rest)
    elif cmd == "analyze":
        ap = argparse.ArgumentParser()
        ap.add_argument("--data", type=Path, default=Path("data"))
        ap.add_argument("--out", type=Path, default=Path("reports"))
        a = ap.parse_args(rest)
        from .analysis import write_report
        print(write_report(a.data, a.out))
    elif cmd == "select":
        ap = argparse.ArgumentParser()
        ap.add_argument("--data", type=Path, default=Path("data"))
        ap.add_argument("--graph", type=Path, required=True, help="edge list file")
        ap.add_argument("--task", default="certified",
                        choices=["certified", "optimum", "budgeted", "approx"])
        a = ap.parse_args(rest)
        from .selector import AlgorithmSelector
        import networkx as nx
        G = nx.convert_node_labels_to_integers(nx.read_edgelist(a.graph, nodetype=str))
        sel = AlgorithmSelector.train(a.data, task=a.task)
        name, why = sel.explain(G)
        print(f"selected: {name}\nreason:   {why}")
        res = sel.solve(G)
        print(f"cover size: {len(res.cover)}  certified optimal: {res.proved_optimal}")
    else:
        sys.exit(f"unknown command {cmd!r}\n{__doc__}")


if __name__ == "__main__":
    main()
