from cybertwin.scenarios.whatif import (compromise_host, link_failure, router_failure,
                                        run_whatif, traffic_surge)
from cybertwin.sim.flow import simulate, summarize


def test_baseline_is_healthy(net):
    res = simulate(net)
    s = summarize(net, res)
    assert s["service_loss"] == 0.0
    assert s["unreachable"] == []
    assert s["max_util"] < 0.8
    # users reach the DB server via r1-r2-r3 (4 ms) rather than the 6 ms direct link
    assert res.paths["backup:h2>srv2"][2:5] == ["r1", "r2", "r3"]


def test_core_link_failure_reroutes_over_backup_path(net):
    after = link_failure(net, "r2", "r3")
    res = simulate(after)
    assert "r1" in res.paths["db:h3>srv2"] and "r2" not in res.paths["db:h3>srv2"]
    assert res.reachable["db:h3>srv2"]
    base = simulate(net)
    assert res.latency["db:h3>srv2"] > base.latency["db:h3>srv2"]


def test_router_failure_can_partition(net):
    after = router_failure(net, "r2")                 # srv1 hangs off r2 only
    res = simulate(after)
    assert not res.reachable["web:h1>srv1"]
    assert res.reachable["db:h3>srv2"]                # srv2 still reachable via r1-r3
    assert summarize(after, res)["service_loss"] > 0


def test_surge_causes_congestion_and_loss(net):
    after = traffic_surge(net, factor=4.0)
    res = simulate(after)
    s = summarize(after, res)
    assert s["congested_links"] and s["service_loss"] > 0.1
    assert max(res.loss.values()) > 0


def test_isolation_removes_flows_and_rate_limit_scales_them(net):
    n = net.clone()
    n.graph.nodes["h2"]["isolated"] = True
    res = simulate(n)
    assert not res.reachable["web:h2>srv1"] and res.delivered["web:h2>srv1"] == 0.0
    m = net.clone()
    m.graph.nodes["h2"]["rate_limit"] = 0.5
    assert abs(simulate(m).delivered["web:h2>srv1"] - 10.0) < 1e-9


def test_scenarios_do_not_mutate_the_original(net):
    link_failure(net, "r2", "r3")
    router_failure(net, "r1")
    compromise_host(net, "h2")
    assert net.graph.edges["r2", "r3"]["up"] and net.graph.nodes["r1"]["up"]
    assert not any(d.malicious for d in net.demands)


def test_run_whatif_compromise_reports_lateral_exposure(net):
    out = run_whatif(net, "compromise", host="h2", exfil_mbps=120.0, target="srv2")
    assert out["lateral"]["risk"] > 1.0
    assert "srv2" in out["lateral"]["exposed"]
