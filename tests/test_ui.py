import json
import threading
import urllib.error
import urllib.request

import pytest

from cybertwin.ui import service
from cybertwin.ui.server import make_server


def test_topology_view_has_every_node_and_link(net):
    t = service.topology()
    assert {n["id"] for n in t["view"]["nodes"]} == set(net.graph.nodes)
    assert len(t["view"]["links"]) == net.graph.number_of_edges()
    assert t["kpi"]["service_loss"] == 0.0


def test_whatif_link_failure_marks_link_down():
    out = service.whatif("link_failure", {"a": "r2", "b": "r3"})
    link = next(l for l in out["after"]["view"]["links"] if l["id"] == "r2|r3")
    assert link["up"] is False
    assert any(f["after"]["path"] != f["before"]["path"] for f in out["flows"])


def test_whatif_compromise_reports_lateral_exposure():
    out = service.whatif("compromise", {"host": "h2", "target": "srv2", "exfil_mbps": 120})
    assert out["lateral"]["risk"] > 1.0
    assert any(x["node"] == "srv2" for x in out["lateral"]["exposed"])


@pytest.mark.parametrize("scenario,args", [
    ("link_failure", {"a": "h1", "b": "r3"}),          # no such link
    ("router_failure", {"node": "h1"}),                # hosts are not routers/switches
    ("surge", {"factor": 9999}),                       # out of range
    ("compromise", {"host": "srv1", "target": "srv2"}),  # attacker must be a host
    ("nope", {}),
])
def test_whatif_rejects_bad_input(scenario, args):
    with pytest.raises(service.InputError):
        service.whatif(scenario, args)


def test_incident_runs_and_isolates_attacker(tmp_path):
    run = service.run_incident(seed=0, attacker="h2", log_dir=tmp_path)
    assert [e["type"] for e in run["events"]] == ["warmup", "monitor", "attack", "detect", "candidates", "act", "verify"]
    assert run["summary"]["chosen"] == "isolate_host[h2]"
    assert run["meta"]["dry_run"] is True
    assert any(n["compromised"] for n in run["views"]["attack"]["nodes"])
    assert next(n for n in run["views"]["after"]["nodes"] if n["id"] == "h2")["isolated"]
    json.dumps(run)                                     # must be serialisable for the browser
    hist = service.history(tmp_path)
    assert hist["audit"] and hist["fidelity"]


def test_incident_rejects_non_host_attacker(tmp_path):
    with pytest.raises(service.InputError):
        service.run_incident(attacker="srv1", log_dir=tmp_path)


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.headers, r.read()


def _post(url, obj):
    req = urllib.request.Request(url, json.dumps(obj).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_serves_index_and_assets(server):
    s, h, body = _get(server + "/")
    assert s == 200 and b"CyberTwin" in body and "text/html" in h["Content-Type"]
    assert _get(server + "/static/app.js")[0] == 200
    assert _get(server + "/static/style.css")[0] == 200


def test_http_api_roundtrip_and_errors(server):
    assert json.loads(_get(server + "/api/topology")[2])["view"]["nodes"]
    s, out = _post(server + "/api/whatif", {"scenario": "surge", "args": {"factor": 3}})
    assert s == 200 and out["after"]["kpi"]["max_util"] > out["before"]["kpi"]["max_util"]
    s, out = _post(server + "/api/whatif", {"scenario": "link_failure", "args": {"a": "x", "b": "y"}})
    assert s == 400 and "error" in out
    assert _post(server + "/api/incident", {"attacker": "srv1"})[0] == 400
    assert _post(server + "/api/incident", {"seed": "abc"})[0] == 400


def test_http_blocks_path_traversal(server):
    for p in ("/static/../server.py", "/static/..%2fserver.py", "/static/%2e%2e/service.py"):
        try:
            code = _get(server + p)[0]
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 404
