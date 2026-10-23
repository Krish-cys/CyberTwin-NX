import json
import re

import pytest
import yaml

from cybertwin.actuator.actuator import Actuator
from cybertwin.ai.actions import Action
from cybertwin.lab.addressing import build_addressing
from cybertwin.lab.clab import render


def test_addressing_is_unique_and_complete(raw):
    addr = build_addressing(raw)
    all_ips = [ip.split("/")[0] for node in addr["ips"].values() for ip in node.values()]
    assert len(all_ips) == len(set(all_ips))
    for n, a in raw["nodes"].items():
        if a["role"] in ("host", "server"):
            assert n in addr["primary"] and n in addr["gateways"]
    # every link end has an interface and (unless on a switch) an IP
    for l in raw["links"]:
        assert addr["ifaces"][l["a"]][l["b"]].startswith("eth")


def test_clab_yaml_matches_topology(raw):
    files = render(raw)
    doc = yaml.safe_load(files["cybertwin.clab.yml"])
    nodes = doc["topology"]["nodes"]
    assert set(nodes) == set(raw["nodes"])
    assert len(doc["topology"]["links"]) == len(raw["links"])
    seen = set()
    for l in doc["topology"]["links"]:
        for ep in l["endpoints"]:
            assert ep not in seen, f"interface {ep} used twice"
            seen.add(ep)
    assert "configs/r1/frr.conf" in files and "ospf" in files["configs/r1/frr.conf"]


def test_isolate_host_plan_targets_first_hop_router(raw):
    act = Actuator(raw)
    plan = act.plan(Action("isolate_host", "h2"))
    ip = build_addressing(raw)["primary"]["h2"]
    assert all(c[:3] == ["docker", "exec", "clab-cybertwin-r1"] for c in plan["apply"])
    assert any(ip in c for c in plan["apply"]) and len(plan["rollback"]) == len(plan["apply"])


def test_dry_run_never_executes_and_writes_audit(raw, tmp_path):
    calls = []
    act = Actuator(raw, dry_run=True, audit_path=tmp_path / "audit.jsonl", runner=calls.append)
    rec = act.execute(Action("isolate_host", "h2"), reason="test")
    assert calls == [] and rec["status"] == "planned"
    assert json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])["action"] == "isolate_host[h2]"


def test_live_mode_runs_commands_and_rolls_back_on_failure(raw):
    calls = []

    def flaky(argv):
        calls.append(argv)
        # argv = ["docker", "exec", <container>, <command>, ...]
        if argv[3] == "iptables" and "-I" in argv and "-d" in argv:      # 2nd rule fails
            raise RuntimeError("boom")
        return ""

    act = Actuator(raw, dry_run=False, runner=flaky)
    rec = act.execute(Action("isolate_host", "h2"))
    assert rec["status"].startswith("failed+rolled_back")
    undone = [c for c in calls if "-D" in c]
    assert len(undone) == 2                         # the rule that applied AND the one that failed


def test_unsafe_node_names_are_rejected(raw):
    act = Actuator(raw)
    with pytest.raises(ValueError):
        act._exec("h2; rm -rf /", "true")


def test_other_action_kinds_plan_sensible_commands(raw):
    act = Actuator(raw)
    assert act.plan(Action("rate_limit_host", "h1", 0.1))["apply"][0][3:5] == ["tc", "qdisc"]
    assert act.plan(Action("isolate_segment", "s1"))["apply"][0][-2:] == ["br0", "down"]
    reroute = act.plan(Action("reroute_avoid_link", "r1|r3", 10.0))
    assert len(reroute["apply"]) == 2 and re.search(r"ip ospf cost 100", " ".join(reroute["apply"][0]))
    assert act.plan(Action("no_op")) == {"apply": [], "rollback": []}
