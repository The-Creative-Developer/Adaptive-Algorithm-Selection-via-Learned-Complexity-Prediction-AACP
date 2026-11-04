import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from aacp.web.server import App, make_handler

DATA = Path(__file__).resolve().parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "runs.csv").exists(), reason="benchmark data missing")


@pytest.fixture(scope="module")
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(DATA)))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_static_and_meta(base):
    code, ctype, body = get(base + "/")
    assert code == 200 and "text/html" in ctype and b"Which algorithm" in body
    assert get(base + "/app.js")[0] == 200
    meta = json.loads(get(base + "/api/meta")[2])
    assert set(meta["trees"]) == {"certified", "optimum", "budgeted"}
    assert len(meta["algorithms"]) == 7


def test_path_traversal_blocked(base):
    import http.client
    host, port = base.rsplit("/", 1)[1].split(":")
    c = http.client.HTTPConnection(host, int(port))
    c.request("GET", "/../server.py")
    assert c.getresponse().status == 404


def test_generate_select_and_run(base):
    code, g = post(base + "/api/generate", {"family": "bipartite", "n": 60, "params": {"p": 0.1, "frac": 0.5}})
    assert code == 200 and g["n"] == 60 and len(g["layout"]) == 60
    sel = g["selection"]["certified"]
    assert sel["choice"] in meta_algos() and sel["steps"]
    code, r = post(base + "/api/run", {"n": g["n"], "edges": g["edges"], "budget": 3})
    assert code == 200 and len(r["results"]) == 7
    proved = {x["size"] for x in r["results"] if x.get("proved")}
    assert len(proved) == 1  # all certified answers agree


def meta_algos():
    from aacp.algorithms import PORTFOLIO
    return set(PORTFOLIO)


def test_parse_and_errors(base):
    code, g = post(base + "/api/parse", {"text": "a b\nb c # comment\nc a\n"})
    assert code == 200 and g["n"] == 3 and g["m"] == 3
    assert post(base + "/api/parse", {"text": "   "})[0] == 400
    assert post(base + "/api/generate", {"family": "nope"})[0] == 400


def test_trap_and_findings(base):
    code, t = post(base + "/api/trap", {"k": 12, "noise": 0})
    assert code == 200 and len(t["opt_cover"]) == 12
    assert len(t["greedy_order"]) == sum(12 // i for i in range(2, 13))
    f = json.loads(get(base + "/api/findings")[2])
    assert f["n_instances"] == 648 and f["bnb"]["rho"]["above_lp"] > f["bnb"]["rho"]["k"]
