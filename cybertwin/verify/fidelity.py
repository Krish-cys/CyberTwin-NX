"""Twin-vs-reality verification: how wrong was the prediction?"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from cybertwin.sim.flow import SimResult
from cybertwin.telemetry.schema import Telemetry


def compare(pred: SimResult, tel: Telemetry, calib=None) -> dict:
    """Latency MAPE, loss MAE, link-utilisation MAE and reachability accuracy."""
    lat_err, loss_err, reach_ok, util_err = [], [], [], []
    for name, ok in tel.flow_reachable.items():
        reach_ok.append(pred.reachable.get(name, False) == ok)
        loss_err.append(abs(pred.loss.get(name, 1.0) - tel.flow_loss.get(name, 1.0)))
        obs = tel.flow_latency.get(name)
        if ok and obs and name in pred.latency:
            p = calib(pred.latency[name]) if calib else pred.latency[name]
            lat_err.append(abs(p - obs) / obs)
    for k, u in tel.link_util.items():
        util_err.append(abs(pred.util.get(k, 0.0) - u))
    mean = lambda xs: float(np.mean(xs)) if xs else 0.0
    return {"latency_mape": mean(lat_err), "loss_mae": mean(loss_err),
            "util_mae": mean(util_err), "reach_acc": mean(reach_ok) if reach_ok else 1.0}


def observed_summary(tel: Telemetry, baseline_flows: set, exclude_src: str | None = None) -> dict:
    """Service loss / leaked exfil measured from telemetry.

    Must use the SAME definitions as ai/scorer.py, including excluding the suspect's own
    flows from 'collateral' service loss -- otherwise predicted-vs-actual is apples to oranges.
    """
    legit = [n for n in tel.flows if n in baseline_flows and tel.flows[n]["src"] != exclude_src]
    mal = [n for n in tel.flows if n not in baseline_flows]
    wsum = sum(tel.flows[n]["priority"] * tel.flows[n]["mbps"] for n in legit) or 1.0
    lost = sum(tel.flows[n]["priority"] * max(0.0, tel.flows[n]["mbps"] - tel.flow_delivered[n]) for n in legit)
    mal_total = sum(tel.flows[n]["mbps"] for n in mal)
    exfil = sum(tel.flow_delivered[n] for n in mal) / mal_total if mal_total else 0.0
    return {"service_loss": lost / wsum, "exfil": exfil}


class FidelityLog:
    """Append-only JSONL so fidelity can be plotted/analysed after a run."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.rows: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **record) -> None:
        record = {"ts": time.time(), **record}
        self.rows.append(record)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
