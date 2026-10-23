"""Multi-objective scoring of simulated outcomes (lower total = better)."""
from __future__ import annotations

from dataclasses import dataclass

from cybertwin.ai.actions import Action, apply_action
from cybertwin.model import Network
from cybertwin.scenarios.lateral import residual_risk
from cybertwin.sim.flow import SimParams, SimResult, simulate, summarize


@dataclass
class Weights:
    service: float = 1.0   # collateral damage to legitimate traffic
    exfil: float = 1.0     # share of malicious traffic still getting through
    risk: float = 1.0      # residual lateral-movement exposure vs doing nothing
    cost: float = 0.3      # intrinsic cost of the action


@dataclass
class Evaluated:
    action: Action
    components: dict
    total: float
    result: SimResult


def evaluate(net: Network, action: Action, suspect: str | None, params: SimParams,
             weights: Weights, base_risk: float) -> Evaluated:
    after = apply_action(net, action)
    res = simulate(after, params)
    mal = [d for d in after.demands if d.malicious]
    mal_total = sum(d.mbps for d in mal)
    exfil = (sum(res.delivered.get(d.name, 0.0) for d in mal) / mal_total) if mal_total else 0.0
    risk = (residual_risk(after, suspect) / base_risk) if (suspect and base_risk) else 0.0
    comps = {
        "service_loss": summarize(after, res, exclude_src=suspect)["service_loss"],
        "exfil": exfil,
        "risk": risk,
        "cost": action.cost,
    }
    total = (weights.service * comps["service_loss"] + weights.exfil * comps["exfil"]
             + weights.risk * comps["risk"] + weights.cost * comps["cost"])
    return Evaluated(action, comps, total, res)


def rank(net: Network, candidates: list[Action], suspect: str | None,
         params: SimParams, weights: Weights | None = None) -> list[Evaluated]:
    w = weights or Weights()
    base_risk = residual_risk(net, suspect)
    out = [evaluate(net, a, suspect, params, w, base_risk) for a in candidates]
    return sorted(out, key=lambda e: e.total)
