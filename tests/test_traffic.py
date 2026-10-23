import pytest

from cybertwin.lab.traffic import plan_attack, plan_start, plan_stop


def test_start_plan_has_a_server_and_a_client_per_demand(raw):
    cmds = plan_start(raw)
    n = len(raw["demands"])
    assert len(cmds) == 2 * n
    assert sum("-s" in c for c in cmds) == n
    clients = [c for c in cmds if "-c" in c]
    assert all(c[:3] == ["docker", "exec", "-d"] for c in clients)
    assert any("30M" in c for c in clients)            # web:h1>srv1 offered load


def test_stop_plan_covers_every_endpoint(raw):
    ends = [n for n, a in raw["nodes"].items() if a["role"] in ("host", "server")]
    assert len(plan_stop(raw)) == len(ends)


def test_attack_plan_scans_only_the_hosts_own_segment(raw):
    cmds = plan_attack(raw, "h2", "srv2", 120)
    assert any("10.1.1.0/24" in c for c in cmds) and not any("10.1.2.0/24" in c for c in cmds)
    assert any("120M" in c for c in cmds)


def test_attack_plan_rejects_non_lab_nodes(raw):
    with pytest.raises(ValueError):
        plan_attack(raw, "r1", "srv2")                 # a router is not an endpoint host
    with pytest.raises(ValueError):
        plan_attack(raw, "h2", "8.8.8.8")
