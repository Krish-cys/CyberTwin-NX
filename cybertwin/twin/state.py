"""The digital twin: a continuously synchronised model of the live network."""
from __future__ import annotations

from dataclasses import replace

from cybertwin.ai.corrector import Calibrator
from cybertwin.model import Demand, Network
from cybertwin.sim.flow import SimParams, SimResult, simulate
from cybertwin.telemetry.schema import Telemetry


class TwinState:
    def __init__(self, net: Network, params: SimParams | None = None):
        self.net = net.clone()
        self.params = params or SimParams()
        self.calib = Calibrator()
        self.baseline_flows: set[str] = set()
        self.last_tel: Telemetry | None = None

    # -- synchronisation -------------------------------------------------------
    def sync(self, tel: Telemetry) -> None:
        """Pull topology state and offered load from telemetry into the model."""
        g = self.net.graph
        for key, up in tel.link_up.items():
            g.edges[key]["up"] = up
        for n, st in tel.node_state.items():
            g.nodes[n].update(up=st["up"], isolated=st["isolated"], rate_limit=st["rate_limit"])
        self.net.demands = [
            Demand(name=n, src=f["src"], dst=f["dst"], mbps=f["mbps"],
                   app=f.get("app", "web"), priority=f.get("priority", 1))
            for n, f in tel.flows.items()
        ]
        self.last_tel = tel

    def mark_baseline(self, tel: Telemetry) -> None:
        """Flows seen during the clean warm-up are 'known good'; anything new is suspect."""
        self.baseline_flows.update(tel.flows)

    # -- prediction ------------------------------------------------------------
    def predict(self) -> SimResult:
        return simulate(self.net, self.params)

    def latency_pairs(self, tel: Telemetry) -> list[tuple[float, float]]:
        """(predicted, observed) latency pairs for calibration."""
        res = self.predict()
        return [(res.latency[n], v) for n, v in tel.flow_latency.items() if n in res.latency]

    # -- incident view ---------------------------------------------------------
    def incident_net(self, suspect: str) -> Network:
        """Copy of the twin with `suspect` marked compromised and its NEW flows tagged malicious."""
        n = self.net.clone()
        n.graph.nodes[suspect]["compromised"] = True
        n.demands = [replace(d, malicious=True) if (d.src == suspect and d.name not in self.baseline_flows) else d
                     for d in n.demands]
        return n
