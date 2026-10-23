"""The one telemetry record every source (synthetic or Containerlab) must produce."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Telemetry:
    t: int
    # name -> {src, dst, mbps (OFFERED, measured at the sender), app, priority}
    flows: dict = field(default_factory=dict)
    flow_latency: dict = field(default_factory=dict)     # name -> ms (reachable flows only)
    flow_loss: dict = field(default_factory=dict)        # name -> 0..1
    flow_delivered: dict = field(default_factory=dict)   # name -> Mbps measured at the receiver
    flow_reachable: dict = field(default_factory=dict)   # name -> bool
    link_util: dict = field(default_factory=dict)        # (a,b) -> utilisation
    link_up: dict = field(default_factory=dict)         # (a,b) -> bool
    node_state: dict = field(default_factory=dict)       # node -> {up, isolated, rate_limit}
    host_feats: dict = field(default_factory=dict)       # host -> [out_mbps, fan_out, failed_auth]
