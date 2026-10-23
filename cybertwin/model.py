"""Network model: topology graph + offered demands + attack-graph edges.

NOTE: this file was RECONSTRUCTED on 2026-10-08 after the original was accidentally overwritten.
It was rebuilt from how the rest of the package and the test-suite use it (see git/backup if you
still have the original and prefer that version). Public API:

    ekey(a, b)            -> canonical undirected link key: sorted 2-tuple
    Demand                -> one offered flow (name, src, dst, mbps, app, priority, malicious)
    Network               -> graph + demands + access; .clone() .hosts() .value(node)
    load_raw(path=None)   -> raw dict from data/topology.yaml
    build_network(raw)    -> Network

Graph conventions (relied on by sim/, scenarios/, ai/, telemetry/):
    node attrs: role (router|switch|host|server), zone, value, up=True, isolated=False,
                rate_limit=1.0, compromised=False
    edge attrs: cap_mbps, lat_ms, up=True, penalty=1.0
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

DEFAULT_TOPOLOGY = Path(__file__).resolve().parent.parent / "data" / "topology.yaml"
DEFAULT_HOST_VALUE = 1.0


def ekey(a: str, b: str) -> tuple[str, str]:
    """Canonical key for an undirected link (usable directly as graph.edges[key])."""
    return (a, b) if a <= b else (b, a)


@dataclass
class Demand:
    name: str
    src: str
    dst: str
    mbps: float
    app: str = "web"
    priority: int = 1          # 1 bulk .. 3 critical
    malicious: bool = False


@dataclass
class Network:
    graph: nx.Graph
    demands: list[Demand] = field(default_factory=list)
    access: list[dict] = field(default_factory=list)   # attack-graph edges {src, dst, via, p}

    def clone(self) -> "Network":
        return Network(copy.deepcopy(self.graph), list(self.demands),
                       [dict(e) for e in self.access])

    def hosts(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True) if d.get("role") == "host"]

    def value(self, node: str) -> float:
        """Asset value used to weight lateral-movement risk."""
        return float(self.graph.nodes[node].get("value", 0.0))


def load_raw(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_TOPOLOGY, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_network(raw: dict) -> Network:
    g = nx.Graph()
    for name, attrs in raw["nodes"].items():
        role = attrs["role"]
        value = attrs.get("value", DEFAULT_HOST_VALUE if role == "host" else 0.0)
        g.add_node(name, role=role, zone=attrs.get("zone"), value=float(value),
                   up=True, isolated=False, rate_limit=1.0, compromised=False)
    for l in raw["links"]:
        g.add_edge(l["a"], l["b"], cap_mbps=float(l["cap_mbps"]), lat_ms=float(l["lat_ms"]),
                   up=True, penalty=1.0)
    demands = [Demand(name=d["name"], src=d["src"], dst=d["dst"], mbps=float(d["mbps"]),
                      app=d.get("app", "web"), priority=int(d.get("priority", 1)))
               for d in raw.get("demands", [])]
    access = [dict(e) for e in raw.get("access", [])]
    return Network(g, demands, access)
