"""Zero-dependency web server for the AACP demo (stdlib ``http.server``).

    python -m aacp serve [--port 8000] [--data data] [--open]

JSON API
  GET  /api/meta        portfolio, problem kinds, scenarios, families, presets, trees
  POST /api/generate    {family, n, seed, params}       -> graph (+ layout)
  POST /api/parse       {text}                          -> problem definition (+ layout)
  POST /api/layout      {n, edges}                      -> layout
  POST /api/analyze     problem definition              -> live analysis (reduction, votes, ...)
  POST /api/race        problem + {algorithms, budget}  -> race job (runs in the background)
  GET  /api/race/<id>   streaming status / results;   POST /api/race/<id>/cancel
  POST /api/trap        {k, noise, seed}                -> greedy-trap walkthrough
  GET  /api/findings    benchmark data behind the theory-vs-practice charts
  GET  /api/selection   selector evaluation table
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import threading
import time
import webbrowser
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats

from .. import selection as S
from ..algorithms import EXACT, PORTFOLIO, Deadline, Timeout, is_vertex_cover
from ..algorithms.common import harmonic
from ..algorithms.greedy import greedy_order
from ..algorithms.lp import ilp
from ..features import compute_features
from ..graphs import Spec, greedy_trap, make
from ..problems import KINDS, ProblemError
from .live import LiveModel, RaceManager
from .scenarios import SCENARIOS

STATIC = Path(__file__).parent / "static"
MAX_NODES = 300
DEMO_TASKS = ("certified", "optimum", "budgeted")

FAMILIES = {
    "er":        {"label": "Random (Erdős–Rényi)", "params": {"p": [0.01, 0.6, 0.06]}},
    "ba":        {"label": "Hub-heavy (Barabási–Albert)", "params": {"m": [1, 6, 2]}},
    "ws":        {"label": "Small-world (Watts–Strogatz)", "params": {"k": [2, 10, 4], "beta": [0.0, 1.0, 0.1]}},
    "plc":       {"label": "Clustered power-law (Holme–Kim)", "params": {"m": [1, 6, 2], "pt": [0.0, 1.0, 0.6]}},
    "rgg":       {"label": "Geometric (random geometric)", "params": {"r": [0.05, 0.4, 0.17]}},
    "ktree":     {"label": "Low treewidth (partial k-tree)", "params": {"k": [1, 16, 4], "keep": [0.3, 1.0, 0.8]}},
    "bipartite": {"label": "Bipartite", "params": {"p": [0.01, 0.6, 0.08], "frac": [0.2, 0.5, 0.4]}},
    "sbm":       {"label": "Communities (block model)", "params": {"blocks": [2, 8, 4], "pin": [0.05, 0.8, 0.3], "pout": [0.0, 0.1, 0.01]}},
}
INT_PARAMS = {"m", "k", "blocks"}

PRESETS = [
    {"id": "sparse", "label": "Sparse random", "family": "er", "n": 80, "params": {"p": 0.04}},
    {"id": "hubs", "label": "Hub-heavy network", "family": "ba", "n": 120, "params": {"m": 2}},
    {"id": "smallworld", "label": "Small world", "family": "ws", "n": 100, "params": {"k": 6, "beta": 0.05}},
    {"id": "geo", "label": "Geometric clusters", "family": "rgg", "n": 90, "params": {"r": 0.17}},
    {"id": "wide", "label": "Wide & clustered", "family": "rgg", "n": 120, "params": {"r": 0.25}},
    {"id": "communities", "label": "Communities", "family": "sbm", "n": 100,
     "params": {"blocks": 4, "pin": 0.4, "pout": 0.01}},
    {"id": "bip", "label": "Two-tier (bipartite)", "family": "bipartite", "n": 100,
     "params": {"p": 0.1, "frac": 0.5}},
    {"id": "dense", "label": "Dense & hard", "family": "er", "n": 120, "params": {"p": 0.25}},
]

ALGO_INFO = {
    name: {"paradigm": para, "unit": unit, "bound": bound, "exact": name in EXACT}
    for name, (_, para, unit, bound) in PORTFOLIO.items()
}


# --------------------------------------------------------------------- helpers
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 6)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _layout(G: nx.Graph) -> list[list[float]]:
    n = G.number_of_nodes()
    if n == 0:
        return []
    pos = None
    if 2 < n <= 80 and nx.is_connected(G):
        try:  # evenly spaced, readable labels for the small hand-made problems
            pos = nx.kamada_kawai_layout(G)
        except Exception:  # pragma: no cover
            pos = None
    if pos is None:
        pos = nx.spring_layout(G, seed=7, iterations=120 if n <= 150 else 60)
    xy = np.array([pos[v] for v in range(n)])
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = np.where(hi - lo > 1e-9, hi - lo, 1.0)
    xy = 0.05 + 0.9 * (xy - lo) / span
    return np.round(xy, 4).tolist()


class App:
    def __init__(self, datadir: Path):
        self.datadir = Path(datadir)
        self.data = S.load(self.datadir)
        self.trees = {t: S.fit_cost_tree(self.data, t, "structural", depth=3)[0]
                      for t in DEMO_TASKS}
        self.live = LiveModel(self.data, self.trees)
        self.races = RaceManager(MAX_NODES)

    # ---------------------------------------------------------------- graphs
    def generate(self, body: dict) -> dict:
        fam = body.get("family", "er")
        if fam not in FAMILIES:
            raise ValueError(f"unknown family {fam!r}")
        n = int(np.clip(int(body.get("n", 80)), 10, 250))
        seed = int(body.get("seed", 1))
        params = {}
        for key, (lo, hi, default) in FAMILIES[fam]["params"].items():
            v = float(body.get("params", {}).get(key, default))
            v = min(max(v, lo), hi)
            params[key] = int(round(v)) if key in INT_PARAMS else round(v, 4)
        if fam == "ws":
            params["k"] = max(2, min(params["k"], n - 1))
        if fam == "ktree":
            params["k"] = min(params["k"], n - 2)
        if fam == "sbm":
            params["blocks"] = min(params["blocks"], n // 3)
        G = make(Spec(fam, n, tuple(sorted(params.items())), seed))
        return {"source": {"kind": "generated", "family": fam, "n": n, "seed": seed, "params": params},
                "n": n, "edges": [[int(u), int(v)] for u, v in G.edges()], "layout": _layout(G)}

    def layout(self, body: dict) -> dict:
        n = int(body.get("n", 0))
        if not 0 < n <= MAX_NODES:
            raise ValueError(f"layout needs 1..{MAX_NODES} vertices")
        G = nx.Graph()
        G.add_nodes_from(range(n))
        G.add_edges_from((int(u), int(v)) for u, v in body.get("edges", []) if int(u) != int(v))
        return {"layout": _layout(G)}

    def parse(self, body: dict) -> dict:
        """Text format, one item per line ('#' starts a comment):
             a b        an edge (also 'a,b' or 'a - b')
             a: 5       vertex weight
             a: 5 require | a: forbid | a:   weight / constraint / isolated vertex"""
        text = str(body.get("text", ""))
        if len(text) > 2_000_000:
            raise ValueError("input too large")
        order, idx, edges, weights, require, forbid = [], {}, set(), {}, set(), set()

        def vid(name):
            if name not in idx:
                idx[name] = len(order)
                order.append(name)
            return idx[name]

        for no, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" in line:
                name, rest = line.split(":", 1)
                v = vid(name.strip())
                for tok in rest.replace(",", " ").split():
                    t = tok.lower()
                    if t in ("require", "required", "must", "in"):
                        require.add(v)
                    elif t in ("forbid", "forbidden", "never", "out"):
                        forbid.add(v)
                    else:
                        try:
                            wv = float(tok)
                        except ValueError:
                            raise ValueError(f"line {no}: cannot read {tok!r} (use a number, 'require' or 'forbid')")
                        if not wv > 0:
                            raise ValueError(f"line {no}: weights must be positive")
                        weights[v] = wv
                continue
            tok = line.replace(",", " ").replace(" - ", " ").replace(";", " ").split()
            if len(tok) == 1:
                vid(tok[0])
            elif len(tok) == 2:
                a, b = vid(tok[0]), vid(tok[1])
                if a != b:
                    edges.add((min(a, b), max(a, b)))
            else:
                raise ValueError(f"line {no}: expected 'u v' for an edge or 'name: weight' for a vertex")
        if not order:
            raise ValueError("nothing to read: write one edge 'u v' per line")
        if len(order) > MAX_NODES:
            raise ValueError(f"{len(order)} vertices: the studio accepts at most {MAX_NODES}")
        n = len(order)
        E = sorted(edges)
        G = nx.Graph(); G.add_nodes_from(range(n)); G.add_edges_from(E)
        return {"n": n, "labels": order, "edges": [list(e) for e in E],
                "weights": [weights.get(v, 1.0) for v in range(n)] if weights else None,
                "require": sorted(require), "forbid": sorted(forbid), "layout": _layout(G)}

    def analyze(self, body: dict) -> dict:
        return self.live.analyze(body, MAX_NODES)

    def race(self, body: dict) -> dict:
        return self.races.start(body)

    # ------------------------------------------------------------------ trap
    def trap(self, body: dict) -> dict:
        k = int(np.clip(int(body.get("k", 12)), 3, 40))
        noise = float(np.clip(float(body.get("noise", 0.0)), 0.0, 0.2))
        seed = int(body.get("seed", 1))
        G = greedy_trap(k, noise, seed)
        L = list(range(k))
        blocks, nxt = [], k
        for i in range(2, k + 1):
            for _ in range(k // i):
                blocks.append({"node": nxt, "block": i})
                nxt += 1
        order = greedy_order({v: set(G[v]) for v in G})
        opt_cover = sorted(ilp(G, Deadline(10)).cover)
        return {"k": k, "noise": noise, "L": L, "R": blocks,
                "edges": [[int(u), int(v)] for u, v in G.edges()],
                "greedy_order": [int(v) for v in order], "opt_cover": [int(v) for v in opt_cover],
                "ratio": len(order) / len(opt_cover), "bound": harmonic(k) - 1}

    # -------------------------------------------------------------- findings
    @lru_cache(maxsize=1)
    def findings(self) -> dict:
        inst = pd.read_csv(self.datadir / "instances.csv")
        runs = pd.read_csv(self.datadir / "runs.csv").merge(inst, on="instance")
        runs["ok"] = runs["status"].eq("ok")
        known = runs["opt_source"].isin(["portfolio", "ilp_ref"])
        lp = runs[runs.algorithm == "lp_round"].set_index("instance")["x_lp_value"]
        runs["lp"] = runs["instance"].map(lp)
        runs["ratio"] = runs["size"] / runs["opt"]

        def rho(a, b):
            m = np.isfinite(a) & np.isfinite(b)
            return float(stats.spearmanr(a[m], b[m])[0])

        B = runs[(runs.algorithm == "bnb") & runs.ok & known].copy()
        B["above_lp"] = B["opt"] - B["lp"]
        I = runs[(runs.algorithm == "ilp") & known].copy()
        I["gap"] = I["opt"] - I["lp"]
        D = runs[runs.algorithm == "td_dp"].copy()
        G = runs[(runs.algorithm == "greedy") & known & (runs.family != "trap")].copy()
        budget = json.loads((self.datadir / "meta.json").read_text())["budget"]

        portfolio = []
        for a in PORTFOLIO:
            d = runs[runs.algorithm == a]
            dk = d[known.loc[d.index] & d.ok]
            portfolio.append({"algorithm": a, **ALGO_INFO[a],
                              "solved": float(d.ok.mean()),
                              "median_ms": float(1000 * d[d.ok]["time"].median()),
                              "mean_ratio": float(dk["ratio"].mean()),
                              "max_ratio": float(dk["ratio"].max()),
                              "optimal": float((dk["ratio"] == 1).mean())})
        fam_counts = inst["family"].value_counts().to_dict()
        return _clean({
            "n_instances": len(inst), "budget": budget, "families": fam_counts,
            "portfolio": portfolio,
            "bnb": {"points": [{"k": r.opt, "above_lp": r.above_lp, "n": r.n, "nodes": r.ops,
                         "family": r.family} for r in B.itertuples()],
             "rho": {"n": rho(B["ops"].values, B["n"].values.astype(float)),
                     "k": rho(B["ops"].values, B["opt"].values),
                     "above_lp": rho(B["ops"].values, B["above_lp"].values)}},
            "ilp": {"points": [{"gap": r.gap, "time": r.time, "ok": r.ok, "n": r.n,
                                "family": r.family} for r in I.itertuples()],
                    "rho": {"gap": rho(I[I.ok]["time"].values, I[I.ok]["gap"].values),
                            "n": rho(I[I.ok]["time"].values, I[I.ok]["n"].values.astype(float))}},
            "dp": {"points": [{"tw": r.tw_ub, "time": r.time, "ok": r.ok, "family": r.family}
                              for r in D.itertuples()]},
            "greedy": {"points": [{"clustering": r.clustering, "assortativity": r.assortativity,
                                   "deg_cv": r.deg_cv, "ratio": r.ratio, "family": r.family}
                                  for r in G.itertuples()],
                       "rho": {f: rho(G["ratio"].values, G[f].values)
                               for f in ("clustering", "assortativity", "deg_cv")}},
        })

    @lru_cache(maxsize=1)
    def selection(self) -> dict:
        p = self.datadir.parent / "reports" / "selection_results.csv"
        rows = pd.read_csv(p).to_dict("records") if p.exists() else []
        return _clean({"results": rows})

    def meta(self) -> dict:
        return _clean({
            "algorithms": ALGO_INFO, "families": FAMILIES, "presets": PRESETS,
            "kinds": KINDS, "scenarios": SCENARIOS,
            "tasks": list(DEMO_TASKS), "max_nodes": MAX_NODES,
            "trees": {t: tr.to_dict() for t, tr in self.trees.items()},
            "budget_ms": S.TAU * 1000,
        })


# --------------------------------------------------------------------- server
def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AACP/0.1"

        def log_message(self, fmt, *args):  # quieter console: skip assets and race polling
            if not str(args[0]).startswith(("GET /static", "GET /fonts", "GET /api/race/")):
                super().log_message(fmt, *args)

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser navigated away mid-response

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json")
                             else "max-age=300")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(_clean(obj)).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/api/meta":
                    return self._json(app.meta())
                if path == "/api/findings":
                    return self._json(app.findings())
                if path == "/api/selection":
                    return self._json(app.selection())
                if path.startswith("/api/race/"):
                    return self._json(app.races.get(path.rsplit("/", 1)[1]))
            except ProblemError as e:
                return self._json({"error": str(e)}, 404)
            except Exception as e:  # pragma: no cover
                return self._json({"error": str(e)}, 500)
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (STATIC / rel).resolve()
            if not str(f).startswith(str(STATIC.resolve())) or not f.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if f.suffix == ".woff2":
                ctype = "font/woff2"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, f.read_bytes(), ctype)

        def do_POST(self):
            routes = {"/api/generate": app.generate, "/api/parse": app.parse,
                      "/api/layout": app.layout, "/api/analyze": app.analyze,
                      "/api/race": app.race, "/api/trap": app.trap}
            fn = routes.get(self.path)
            if fn is None and self.path.startswith("/api/race/") and self.path.endswith("/cancel"):
                jid = self.path.split("/")[3]
                fn = lambda _body: app.races.cancel(jid)
            if fn is None:
                return self._json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > 4_000_000:
                    raise ValueError("request too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                return self._json(fn(body))
            except (ValueError, KeyError, TypeError) as e:  # ProblemError is a ValueError
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            except Exception as e:  # pragma: no cover
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def serve(datadir="data", host="127.0.0.1", port=8000, open_browser=False):
    print("training selector trees on", datadir, "...", flush=True)
    app = App(Path(datadir))
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_address[1]}/"
    print(f"AACP demo running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="AACP interactive demo")
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="open a browser tab")
    a = ap.parse_args(argv)
    serve(a.data, a.host, a.port, a.open)


if __name__ == "__main__":
    main()
