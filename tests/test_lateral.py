import pytest

from cybertwin.scenarios.lateral import compromise_probs, residual_risk
from cybertwin.scenarios.whatif import link_failure


def test_probabilities_follow_best_path(net):
    p = compromise_probs(net, "h2")
    assert p["h2"] == 1.0
    assert p["h3"] == pytest.approx(0.40)
    assert p["srv2"] == pytest.approx(0.24)       # h2->h3->srv2 (0.4*0.6) beats h2->srv2 (0.2)
    assert p["srv1"] == pytest.approx(0.30)


def test_isolating_the_start_host_removes_all_risk(net):
    n = net.clone()
    n.graph.nodes["h2"]["isolated"] = True
    assert compromise_probs(n, "h2") == {}
    assert residual_risk(n, "h2") == 0.0


def test_isolating_a_pivot_reduces_risk(net):
    base = residual_risk(net, "h2")
    n = net.clone()
    n.graph.nodes["h3"]["isolated"] = True
    assert residual_risk(n, "h2") < base


def test_network_partition_cuts_attack_paths(net):
    n = net.clone()
    n.graph.nodes["s2"]["up"] = False             # branch segment unreachable
    assert "h4" not in compromise_probs(n, "h2")
    assert "h4" in compromise_probs(net, "h2")


def test_risk_weights_by_asset_value(net):
    # srv2 (value 10) dominates the risk from h2
    p = compromise_probs(net, "h2")
    assert net.value("srv2") * p["srv2"] > sum(net.value(h) * p[h] for h in ("h1", "h3"))
