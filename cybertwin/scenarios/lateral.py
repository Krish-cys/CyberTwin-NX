"""Lateral-movement model: a probabilistic attack graph.

An attacker who owns `start` can reach `dst` along access edges with probability
p(path) = product of edge probabilities; we take the most likely path (Dijkstra on
-log p). Edges only count while both endpoints are up/not isolated AND the network can
actually carry traffic between them -- so isolating a host or failing a router changes
the attack surface, which is exactly what the twin needs to score a response.

The edge probabilities in data/topology.yaml are *assumptions*; replace them with values
derived from vulnerability scans or red-team data for a real evaluation.
"""
from __future__ import annotations

import math

import networkx as nx

from cybertwin.model import Network
from cybertwin.sim.flow import usable_graph


def compromise_probs(net: Network, start: str) -> dict[str, float]:
    g = net.graph
    ug = usable_graph(g)

    def alive(n: str) -> bool:
        return n in ug and not g.nodes[n].get("isolated", False)

    if not alive(start):
        return {}
    ag = nx.DiGraph()
    for e in net.access:
        s, d, p = e["src"], e["dst"], float(e["p"])
        if alive(s) and alive(d) and nx.has_path(ug, s, d):
            ag.add_edge(s, d, w=-math.log(p))
    if start not in ag:
        return {start: 1.0}
    dist = nx.single_source_dijkstra_path_length(ag, start, weight="w")
    return {n: math.exp(-d) for n, d in dist.items()}


def residual_risk(net: Network, start: str | None) -> float:
    """Sum of asset value x compromise probability over everything still exposed."""
    if not start:
        return 0.0
    return sum(net.value(n) * p for n, p in compromise_probs(net, start).items())
