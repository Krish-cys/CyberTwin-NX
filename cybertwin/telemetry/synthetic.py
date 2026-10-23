"""Synthetic stand-in for the real network, so the whole loop runs on a laptop.

IMPORTANT (honesty note): this emulator reuses the same flow simulator as the twin, with
*different hidden parameters* (slower links, extra queueing, unmodelled background load,
noisy counters). Fidelity numbers measured against it validate the PLUMBING and the
calibration step -- they say little about accuracy on a real network. Use the Containerlab
collector (telemetry/containerlab.py) for the evaluation you report.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from cybertwin.ai.actions import Action, apply_action
from cybertwin.model import Network, ekey
from cybertwin.scenarios.whatif import SCENARIOS
from cybertwin.sim.flow import SimParams, simulate
from cybertwin.telemetry.schema import Telemetry

HIDDEN_PARAMS = SimParams(lat_scale=1.15, queue_ms=1.7, bg_mbps=8.0)


class SyntheticEmulator:
    def __init__(self, net: Network, seed: int = 0, params: SimParams | None = None,
                 noise: float = 0.03):
        self.net = net.clone()
        self.params = params or HIDDEN_PARAMS
        self.noise = noise
        self.rng = np.random.default_rng(seed)
        self.t = 0

    # -- events ---------------------------------------------------------------
    def inject(self, kind: str, **kw) -> None:
        """kind: link_failure | router_failure | surge | compromise (see scenarios.whatif)."""
        self.net = SCENARIOS[kind](self.net, **kw)

    def apply_action(self, action: Action) -> None:
        self.net = apply_action(self.net, action)

    # -- observation ----------------------------------------------------------
    def tick(self) -> Telemetry:
        self.t += 1
        r, g = self.rng, self.net.graph
        jittered = [replace(d, mbps=max(0.0, d.mbps * (1 + r.normal(0, 0.05)))) for d in self.net.demands]
        res = simulate(Network(g, jittered, self.net.access), self.params)

        tel = Telemetry(t=self.t)
        for d in jittered:
            tel.flows[d.name] = {"src": d.src, "dst": d.dst, "mbps": d.mbps,
                                 "app": d.app, "priority": d.priority}
            reach = res.reachable.get(d.name, False)
            tel.flow_reachable[d.name] = reach
            tel.flow_loss[d.name] = float(np.clip(res.loss[d.name] + abs(r.normal(0, 0.002)), 0, 1))
            tel.flow_delivered[d.name] = float(min(d.mbps, max(0.0, res.delivered[d.name] * (1 + r.normal(0, self.noise)))))
            if reach:
                tel.flow_latency[d.name] = res.latency[d.name] * (1 + r.normal(0, self.noise))
        for k, u in res.util.items():
            tel.link_util[k] = max(0.0, u + r.normal(0, 0.01))
        for a, b, d in g.edges(data=True):
            tel.link_up[ekey(a, b)] = bool(d["up"])
        for n, d in g.nodes(data=True):
            tel.node_state[n] = {"up": bool(d["up"]), "isolated": bool(d["isolated"]),
                                 "rate_limit": float(d["rate_limit"])}
        for h in self.net.hosts():
            bad = bool(g.nodes[h].get("compromised"))
            out = sum(d.mbps for d in jittered if d.src == h)
            fan = 1 + r.poisson(2) + (int(r.normal(20, 3)) if bad else 0)
            auth = r.poisson(0.3) + (r.poisson(9) if bad else 0)
            tel.host_feats[h] = [out, float(fan), float(auth)]
        return tel
