"""Safety gate between 'the twin likes this action' and 'we touch the real network'.

The twin can be wrong, so every action is reviewed against explicit, auditable rules:
  1. kind must be on the allowlist                      -> otherwise BLOCKED
  2. must beat doing nothing by a clear margin          -> otherwise BLOCKED
  3. never auto-act on protected assets (routers, switches, servers) -> HUMAN
  4. predicted collateral damage must stay under a cap  -> HUMAN
  5. twin fidelity must be recent-and-good (MAPE cap)   -> HUMAN
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cybertwin.ai.actions import Action
from cybertwin.ai.scorer import Evaluated
from cybertwin.model import Network


@dataclass
class GatePolicy:
    allowed_kinds: frozenset = frozenset({"no_op", "rate_limit_host", "isolate_host", "reroute_avoid_link"})
    protected_roles: frozenset = frozenset({"router", "switch", "server"})
    max_service_loss: float = 0.15
    min_improvement: float = 0.20      # fractional drop in total score vs no_op
    max_fidelity_mape: float = 0.35


@dataclass
class Decision:
    approved: bool
    needs_human: bool = False
    blocked: bool = False
    reasons: list = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.approved:
            return "APPROVED"
        return "ESCALATE" if self.needs_human else "BLOCKED"


def review(chosen: Evaluated, no_op: Evaluated, net: Network, fidelity_mape: float,
           policy: GatePolicy | None = None) -> Decision:
    pol = policy or GatePolicy()
    a: Action = chosen.action
    if a.kind == "no_op":
        return Decision(True, reasons=["no action required"])

    blocked, human, why = False, False, []
    if a.kind not in pol.allowed_kinds:
        blocked = True
        why.append(f"action kind '{a.kind}' is not on the allowlist")
    gain = (no_op.total - chosen.total) / no_op.total if no_op.total > 0 else 0.0
    if gain < pol.min_improvement:
        blocked = True
        why.append(f"only {gain:.0%} better than doing nothing (need {pol.min_improvement:.0%})")
    if a.target and a.target in net.graph and net.graph.nodes[a.target]["role"] in pol.protected_roles:
        human = True
        why.append(f"{a.target} is a protected {net.graph.nodes[a.target]['role']}")
    if chosen.components["service_loss"] > pol.max_service_loss:
        human = True
        why.append(f"predicted service loss {chosen.components['service_loss']:.0%} exceeds "
                   f"{pol.max_service_loss:.0%}")
    if fidelity_mape > pol.max_fidelity_mape:
        human = True
        why.append(f"twin fidelity is poor (latency MAPE {fidelity_mape:.0%})")

    if blocked:
        return Decision(False, False, True, why)
    if human:
        return Decision(False, True, False, why)
    return Decision(True, reasons=["passed all safety checks"])
