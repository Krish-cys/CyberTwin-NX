"""Telemetry collector for a REAL (emulated) network running under Containerlab.

STATUS: experimental / untested against a live lab -- written to match the files produced by
`python -m cybertwin gen-lab`. Expect to tweak interface names and parsing on first run.

Signals
  latency/loss : `ping` from each flow's source container to the destination's address
  utilisation  : delta of /sys/class/net/<if>/statistics/{tx,rx}_bytes on both link ends
  link/node up : /sys/class/net/<if>/operstate
  host feats   : tx rate on the host NIC, distinct established peers (`ss`), failed_auth=0 (TODO: parse auth logs)

Offered load per flow is taken from the configured demands (iperf3 -b), which is what the
traffic scripts in lab/scripts/ generate.
"""
from __future__ import annotations

import re
import subprocess
import time

from cybertwin.lab.addressing import build_addressing
from cybertwin.model import Network, ekey
from cybertwin.telemetry.schema import Telemetry

_SAFE = re.compile(r"^[A-Za-z0-9_.:/-]+$")


def _run(argv: list[str], timeout: int = 15) -> str:
    for a in argv:
        if not _SAFE.match(a):
            raise ValueError(f"refusing unsafe argument {a!r}")
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout


class ContainerlabCollector:
    def __init__(self, raw: dict, net: Network, interval_s: float = 5.0):
        self.lab = raw.get("name", "cybertwin")
        self.addr = build_addressing(raw)
        self.net = net
        self.interval = interval_s
        self.t = 0
        self._prev: dict = {}

    def _c(self, node: str) -> str:
        return f"clab-{self.lab}-{node}"

    def _sh(self, node: str, *cmd: str) -> str:
        return _run(["docker", "exec", self._c(node), *cmd])

    def _bytes(self, node: str, iface: str) -> int:
        out = self._sh(node, "cat", f"/sys/class/net/{iface}/statistics/tx_bytes").strip()
        return int(out) if out.isdigit() else 0

    def _ping(self, src: str, dst: str) -> tuple[float | None, float]:
        ip = self.addr["primary"][dst].split("/")[0]
        out = self._sh(src, "ping", "-c", "3", "-W", "1", "-q", ip)
        loss = re.search(r"([\d.]+)% packet loss", out)
        rtt = re.search(r"= [\d.]+/([\d.]+)/", out)
        return (float(rtt.group(1)) / 2 if rtt else None), (float(loss.group(1)) / 100 if loss else 1.0)

    def tick(self) -> Telemetry:
        self.t += 1
        now = time.time()
        tel = Telemetry(t=self.t)
        for d in self.net.demands:
            lat, loss = self._ping(d.src, d.dst)
            tel.flows[d.name] = {"src": d.src, "dst": d.dst, "mbps": d.mbps, "app": d.app, "priority": d.priority}
            tel.flow_reachable[d.name] = lat is not None
            tel.flow_loss[d.name] = loss
            tel.flow_delivered[d.name] = d.mbps * (1 - loss)
            if lat is not None:
                tel.flow_latency[d.name] = lat
        for a, b, d in self.net.graph.edges(data=True):
            ia, ib = self.addr["ifaces"][a][b], self.addr["ifaces"][b][a]
            cur = self._bytes(a, ia) + self._bytes(b, ib)
            prev_cur, prev_t = self._prev.get(ekey(a, b), (cur, now))
            mbps = (cur - prev_cur) * 8 / 1e6 / max(now - prev_t, 1e-6)
            self._prev[ekey(a, b)] = (cur, now)
            tel.link_util[ekey(a, b)] = mbps / d["cap_mbps"]
            state = self._sh(a, "cat", f"/sys/class/net/{ia}/operstate").strip()
            tel.link_up[ekey(a, b)] = state in ("up", "unknown")
        for n in self.net.graph.nodes:
            tel.node_state[n] = {"up": True, "isolated": False, "rate_limit": 1.0}   # TODO: read firewall/tc state
        for h in self.net.hosts():
            peers = self._sh(h, "ss", "-Htn", "state", "established").split("\n")
            fan = len({ln.split()[-1].rsplit(":", 1)[0] for ln in peers if ln.strip()})
            out = sum(d.mbps for d in self.net.demands if d.src == h)
            tel.host_feats[h] = [out, float(fan), 0.0]
        time.sleep(self.interval)
        return tel
