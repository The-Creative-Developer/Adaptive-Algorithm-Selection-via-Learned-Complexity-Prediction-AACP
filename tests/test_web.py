import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import networkx as nx
import pytest

from aacp.web.server import App, make_handler

DATA = Path(__file__).resolve().parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "runs.csv").exists(), reason="benchmark data missing")


@pytest.fixture(scope="module")
def app():
    a = App(DATA)
    assert a.live.wait_ready(180)
    return a


@pytest.fixture(scope="module")
def base(app):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_race(base, jid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, _, b = get(f"{base}/api/race/{jid}")
        job = json.loads(b)
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("race did not finish")


def test_static_and_meta(base):
    code, ctype, body = get(base + "/")
    assert code == 200 and "text/html" in ctype and b"Problem studio" in body
    for f in ("app.js", "studio.js", "common.js", "charts.js", "fonts.css"):
        assert get(f"{base}/{f}")[0] == 200
    meta = json.loads(get(base + "/api/meta")[2])
    assert set(meta["trees"]) == {"certified", "optimum", "budgeted"}
    assert set(meta["kinds"]) == {"vertex_cover", "independent_set", "clique"}
    assert len(meta["scenarios"]) == 4 and len(meta["algorithms"]) == 7


def test_path_traversal_blocked(base):
    host, port = base.rsplit("/", 1)[1].split(":")
    c = http.client.HTTPConnection(host, int(port))
    c.request("GET", "/../server.py")
    assert c.getresponse().status == 404


def test_analyze_votes_and_reduction(base):
    G = nx.random_geometric_graph(70, 0.2, seed=2)
    code, a = post(base + "/api/analyze", {"kind": "independent_set", "n": 70, "edges": list(G.edges())})
    assert code == 200 and not a.get("trivial")
    assert a["reduction"]["kernel_n"] == 70 and a["reduction"]["vc_m"] == G.number_of_edges()
    for t in ("certified", "optimum", "budgeted"):
        c = a["tasks"][t]["consensus"]
        assert c["choice"] in {"td_dp", "bnb", "ilp", "greedy", "matching", "lp_round", "nt_flow"}
        assert 0 <= c["confidence"] <= 1 and len(c["votes"]) == 3
        assert len(a["tasks"][t]["neighbours"]) >= 5
    assert set(a["percentiles"]) and a["ehm_ready"]


def test_analyze_errors_and_trivial(base):
    code, e = post(base + "/api/analyze", {"kind": "clique", "n": 3, "edges": [[0, 1]], "require": [0, 2]})
    assert code == 400 and "infeasible" in e["error"]
    code, a = post(base + "/api/analyze", {"kind": "vertex_cover", "n": 3, "edges": [[0, 1], [1, 2]], "require": [1]})
    assert code == 200 and a["trivial"]


def test_race_streams_and_verifies(base):
    sc = json.loads(get(base + "/api/meta")[2])["scenarios"][1]  # weighted patch plan with constraints
    body = {k: sc[k] for k in ("kind", "edges", "weights", "require", "forbid", "labels")} | {"n": len(sc["labels"]), "budget": 3}
    code, job = post(base + "/api/race", body)
    assert code == 200 and job["status"] == "running"
    job = wait_race(base, job["id"])
    assert job["status"] == "done" and len(job["results"]) == 7
    exact = {r["objective"] for r in job["results"] if r["status"] == "ok" and r["proved"]}
    assert len(exact) == 1 and all(r["feasible"] for r in job["results"] if r["status"] == "ok")
    assert job["best"]["certified"] and job["best"]["objective"] == exact.pop()


def test_race_cancel(base):
    G = nx.gnp_random_graph(170, 0.12, seed=4)
    code, job = post(base + "/api/race", {"kind": "vertex_cover", "n": 170, "edges": list(G.edges()),
                                          "algorithms": ["bnb"], "budget": 25})
    assert code == 200
    time.sleep(0.4)
    assert post(f"{base}/api/race/{job['id']}/cancel", {})[0] == 200
    t0 = time.time()
    job = wait_race(base, job["id"], 10)
    assert job["status"] == "cancelled" and time.time() - t0 < 5
    assert get(base + "/api/race/doesnotexist")[0] == 404


def test_parse_syntax_and_layout(base):
    code, d = post(base + "/api/parse", {"text": "web db\nweb cache  # c\ndb backup\ndb: 8 require\nbackup: forbid\nlonely:\n"})
    assert code == 200 and d["n"] == 5 and len(d["edges"]) == 3
    assert d["weights"][d["labels"].index("db")] == 8 and d["require"] == [d["labels"].index("db")]
    assert d["forbid"] == [d["labels"].index("backup")] and len(d["layout"]) == 5
    assert post(base + "/api/parse", {"text": "a b c"})[0] == 400
    assert post(base + "/api/parse", {"text": "a: -3"})[0] == 400
    code, lay = post(base + "/api/layout", {"n": 4, "edges": [[0, 1], [2, 3]]})
    assert code == 200 and len(lay["layout"]) == 4


def test_generate_trap_and_findings(base):
    code, g = post(base + "/api/generate", {"family": "bipartite", "n": 60, "params": {"p": 0.1, "frac": 0.5}})
    assert code == 200 and g["n"] == 60 and len(g["layout"]) == 60
    assert post(base + "/api/generate", {"family": "nope"})[0] == 400
    code, t = post(base + "/api/trap", {"k": 12, "noise": 0})
    assert code == 200 and len(t["opt_cover"]) == 12
    assert len(t["greedy_order"]) == sum(12 // i for i in range(2, 13))
    f = json.loads(get(base + "/api/findings")[2])
    assert f["n_instances"] == 648 and f["bnb"]["rho"]["above_lp"] > f["bnb"]["rho"]["k"]
