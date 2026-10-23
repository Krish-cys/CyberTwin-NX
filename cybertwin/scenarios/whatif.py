"""What-if scenarios. Every function takes a Network and returns a NEW Network."""
from __future__ import annotations

from dataclasses import replace

from cybertwin.model import Demand, Network
from cybertwin.scenarios.lateral import compromise_probs, residual_risk
from cybertwin.sim.flow import SimParams, simulate, summarize


def link_failure(net: Network, a: str, b: str) -> Network:
    n = net.clone()
    n.graph.edges[a, b]["up"] = False
    return n


def router_failure(net: Network, node: str) -> Network:
    n = net.clone()
    n.graph.nodes[node]["up"] = False
    return n


def traffic_surge(net: Network, factor: float = 2.0, dst: str | None = None) -> Network:
    n = net.clone()
    n.demands = [replace(d, mbps=d.mbps * float(factor)) if dst in (None, d.dst) else d
                 for d in n.demands]
    return n


def compromise_host(net: Network, host: str, exfil_mbps: float = 120.0, target: str = "srv2") -> Network:
    """Host owned by an attacker: bulk exfiltration towards `target` (+ lateral risk)."""
    n = net.clone()
    n.graph.nodes[host]["compromised"] = True
    n.demands = n.demands + [Demand(name=f"exfil:{host}>{target}", src=host, dst=target,
                                    mbps=float(exfil_mbps), app="exfil", priority=1, malicious=True)]
    return n


SCENARIOS = {
    "link_failure": link_failure,
    "router_failure": router_failure,
    "surge": traffic_surge,
    "compromise": compromise_host,
}


def run_whatif(net: Network, scenario: str, params: SimParams | None = None, **kw) -> dict:
    """Simulate `scenario` and report before/after KPIs."""
    if scenario not in SCENARIOS:
        raise KeyError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    after = SCENARIOS[scenario](net, **kw)
    out = {"scenario": scenario, "args": kw,
           "before": summarize(net, simulate(net, params)),
           "after": summarize(after, simulate(after, params))}
    if scenario == "compromise":
        probs = compromise_probs(after, kw["host"])
        out["lateral"] = {"risk": residual_risk(after, kw["host"]),
                          "exposed": {k: round(v, 3) for k, v in sorted(probs.items(), key=lambda kv: -kv[1])}}
    return out
