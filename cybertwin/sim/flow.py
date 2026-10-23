"""Flow-level network simulator (deliberately NOT learned).

Model
-----
* Routing   : shortest path on lat_ms * penalty over links/nodes that are up (OSPF-like).
* Load      : each reachable flow adds its (rate-limited) Mbps to every link on its path.
              Links are undirected, so both directions share one capacity -- a conservative
              simplification that over-estimates congestion on full-duplex links.
* Latency   : sum(prop_delay * lat_scale + queue_ms * u/(1-u)), u capped at 0.98.
* Loss      : link loss = 1 - 1/util when util > 1; flow loss compounds along the path.
* Isolation : flows from/to an isolated node are dropped (unreachable).

SimParams are the knobs the twin can mis-estimate; the Calibrator in ai/corrector.py
learns a correction from observed telemetry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx

from cybertwin.model import Network, ekey


@dataclass
class SimParams:
    lat_scale: float = 1.0     # multiplier on configured propagation delay
    queue_ms: float = 1.0      # queueing-delay scale
    bg_mbps: float = 0.0       # unmodelled background load added to every link


@dataclass
class SimResult:
    util: dict = field(default_factory=dict)        # (a,b) -> utilisation (1.0 = full)
    latency: dict = field(default_factory=dict)     # flow -> ms (reachable flows only)
    loss: dict = field(default_factory=dict)        # flow -> 0..1
    delivered: dict = field(default_factory=dict)   # flow -> Mbps delivered
    reachable: dict = field(default_factory=dict)   # flow -> bool
    paths: dict = field(default_factory=dict)       # flow -> [nodes]


def usable_graph(g: nx.Graph) -> nx.Graph:
    """Routing view of the topology: only nodes/links that are up."""
    h = nx.Graph()
    for n, d in g.nodes(data=True):
        if d.get("up", True):
            h.add_node(n)
    for a, b, d in g.edges(data=True):
        if d.get("up", True) and a in h and b in h:
            h.add_edge(a, b, weight=d["lat_ms"] * d.get("penalty", 1.0))
    return h


def simulate(net: Network, params: SimParams | None = None) -> SimResult:
    p = params or SimParams()
    g = net.graph
    ug = usable_graph(g)
    res = SimResult()
    load: dict = defaultdict(float)
    eff: dict = {}

    for d in net.demands:
        s, t = g.nodes[d.src], g.nodes[d.dst]
        if s.get("isolated") or t.get("isolated") or d.src not in ug or d.dst not in ug:
            res.reachable[d.name] = False
            continue
        try:
            path = nx.shortest_path(ug, d.src, d.dst, weight="weight")
        except nx.NetworkXNoPath:
            res.reachable[d.name] = False
            continue
        mbps = d.mbps * s.get("rate_limit", 1.0)
        res.reachable[d.name] = True
        res.paths[d.name] = path
        eff[d.name] = mbps
        for a, b in zip(path, path[1:]):
            load[ekey(a, b)] += mbps

    for a, b, d in g.edges(data=True):
        k = ekey(a, b)
        res.util[k] = (load.get(k, 0.0) + p.bg_mbps) / d["cap_mbps"]
    link_loss = {k: (1.0 - 1.0 / u if u > 1.0 else 0.0) for k, u in res.util.items()}

    for name, path in res.paths.items():
        lat, keep = 0.0, 1.0
        for a, b in zip(path, path[1:]):
            k = ekey(a, b)
            u = min(res.util[k], 0.98)
            lat += g.edges[a, b]["lat_ms"] * p.lat_scale + p.queue_ms * u / (1.0 - u)
            keep *= 1.0 - link_loss[k]
        res.latency[name] = lat
        res.loss[name] = 1.0 - keep
        res.delivered[name] = eff[name] * keep

    for d in net.demands:                     # unreachable flows: total loss
        if not res.reachable.get(d.name):
            res.loss[d.name] = 1.0
            res.delivered[d.name] = 0.0
    return res


def summarize(net: Network, res: SimResult, exclude_src: str | None = None) -> dict:
    """Headline KPIs over *legitimate* traffic, priority-weighted.

    `exclude_src` drops flows originating at that node: when a host is compromised, its own
    traffic is untrusted, so losing it is not counted as collateral damage.
    """
    legit = [d for d in net.demands if not d.malicious and d.src != exclude_src]
    wsum = sum(d.priority * d.mbps for d in legit) or 1.0
    lost = sum(d.priority * max(0.0, d.mbps - res.delivered.get(d.name, 0.0)) for d in legit)
    lats = [res.latency[d.name] for d in legit if d.name in res.latency]
    return {
        "service_loss": lost / wsum,
        "max_util": max(res.util.values(), default=0.0),
        "mean_latency_ms": sum(lats) / len(lats) if lats else 0.0,
        "unreachable": [d.name for d in legit if not res.reachable.get(d.name)],
        "congested_links": sorted(k for k, u in res.util.items() if u > 1.0),
    }
