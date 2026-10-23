"""Candidate response actions and how each one changes the (simulated) network."""
from __future__ import annotations

from dataclasses import dataclass

from cybertwin.model import Network
from cybertwin.sim.flow import SimResult

# Relative operational cost/blast radius of *taking* the action (0..1), used in scoring.
COST = {
    "no_op": 0.0,
    "reroute_avoid_link": 0.10,
    "rate_limit_host": 0.20,
    "isolate_host": 0.40,
    "isolate_segment": 0.80,
}


@dataclass(frozen=True)
class Action:
    kind: str
    target: str = ""      # node name, or "a|b" for a link
    param: float = 0.0    # rate_limit fraction / routing-penalty multiplier

    @property
    def cost(self) -> float:
        return COST[self.kind]

    @property
    def label(self) -> str:
        if self.kind == "no_op":
            return "no_op"
        extra = f"({self.param:g})" if self.param else ""
        return f"{self.kind}[{self.target}]{extra}"


def apply_action(net: Network, a: Action) -> Network:
    n = net.clone()
    g = n.graph
    if a.kind == "no_op":
        pass
    elif a.kind == "isolate_host":
        g.nodes[a.target]["isolated"] = True
    elif a.kind == "rate_limit_host":
        g.nodes[a.target]["rate_limit"] = a.param
    elif a.kind == "isolate_segment":          # shut the access switch
        g.nodes[a.target]["up"] = False
    elif a.kind == "reroute_avoid_link":
        x, y = a.target.split("|")
        g.edges[x, y]["penalty"] = a.param or 10.0
    else:
        raise ValueError(f"unknown action kind {a.kind!r}")
    return n


def _switch_of(net: Network, host: str) -> str | None:
    for nb in net.graph.neighbors(host):
        if net.graph.nodes[nb]["role"] == "switch":
            return nb
    return None


def generate_candidates(net: Network, suspect: str | None = None,
                        baseline: SimResult | None = None) -> list[Action]:
    """Enumerate responses. Deliberately includes some bad ones (isolating the victim
    server, killing the whole segment) so the scorer and safety gate have to earn their keep."""
    acts = [Action("no_op")]
    if suspect:
        acts += [Action("rate_limit_host", suspect, 0.1), Action("isolate_host", suspect)]
        sw = _switch_of(net, suspect)
        if sw:
            acts.append(Action("isolate_segment", sw))
        for d in net.demands:
            if d.malicious and d.src == suspect:
                acts.append(Action("isolate_host", d.dst))
    if baseline:
        for (a, b), u in baseline.util.items():
            core = net.graph.nodes[a]["role"] == "router" and net.graph.nodes[b]["role"] == "router"
            if core and u > 0.85:          # only core links have an alternative path to shift to
                acts.append(Action("reroute_avoid_link", f"{a}|{b}", 10.0))
    return list(dict.fromkeys(acts))
