from cybertwin.ai.actions import Action, apply_action, generate_candidates
from cybertwin.ai.scorer import rank
from cybertwin.safety.gate import GatePolicy, review
from cybertwin.scenarios.whatif import compromise_host
from cybertwin.sim.flow import SimParams, simulate


def _incident(net):
    return compromise_host(net, "h2", exfil_mbps=120.0, target="srv2")


def _ranked(net):
    inc = _incident(net)
    cands = generate_candidates(inc, "h2", simulate(inc))
    return inc, rank(inc, cands, "h2", SimParams())


def test_isolating_the_compromised_host_ranks_first(net):
    _, ranked = _ranked(net)
    assert ranked[0].action == Action("isolate_host", "h2")
    assert ranked[0].components["exfil"] == 0.0 and ranked[0].components["risk"] == 0.0


def test_bad_candidates_are_scored_worse(net):
    _, ranked = _ranked(net)
    by = {e.action.label: e for e in ranked}
    assert by["isolate_segment[s1]"].components["service_loss"] > 0.3
    assert by["isolate_host[srv2]"].components["service_loss"] > 0.3
    assert by["no_op"].total > by["isolate_host[h2]"].total


def test_candidates_include_no_op_and_dedupe(net):
    inc = _incident(net)
    cands = generate_candidates(inc, "h2")
    assert cands[0].kind == "no_op" and len(cands) == len(set(cands))


def test_gate_approves_the_good_action_and_stops_the_bad_ones(net):
    inc, ranked = _ranked(net)
    by = {e.action.label: e for e in ranked}
    no_op = by["no_op"]
    assert review(by["isolate_host[h2]"], no_op, inc, 0.1).verdict == "APPROVED"
    assert review(by["isolate_host[srv2]"], no_op, inc, 0.1).verdict == "ESCALATE"       # protected + collateral
    assert review(by["isolate_segment[s1]"], no_op, inc, 0.1).verdict == "BLOCKED"       # not allowlisted


def test_gate_escalates_when_the_twin_is_unreliable(net):
    inc, ranked = _ranked(net)
    by = {e.action.label: e for e in ranked}
    d = review(by["isolate_host[h2]"], by["no_op"], inc, fidelity_mape=0.9)
    assert d.verdict == "ESCALATE" and any("fidelity" in r for r in d.reasons)


def test_gate_blocks_actions_that_do_not_beat_doing_nothing(net):
    inc, ranked = _ranked(net)
    by = {e.action.label: e for e in ranked}
    strict = GatePolicy(min_improvement=0.999)
    assert review(by["isolate_host[h2]"], by["no_op"], inc, 0.1, strict).verdict == "BLOCKED"


def test_apply_action_is_pure(net):
    apply_action(net, Action("isolate_host", "h2"))
    assert not net.graph.nodes["h2"]["isolated"]
