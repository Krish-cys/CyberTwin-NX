"""Translate approved actions into concrete commands, with rollback and an audit trail.

* DRY-RUN BY DEFAULT: commands are planned and logged, never executed, unless dry_run=False.
* Commands are argv lists (no shell), every token is validated, IPs are parsed with `ipaddress`.
* If any command in an action fails, the commands already applied are rolled back.

Known limitations (documented, not hidden)
  * isolate_host drops traffic at the host's first-hop ROUTER; traffic that stays inside one
    L2 segment is not blocked (needs a host-level or switch ACL).
  * rate_limit_host maps the simulator's fraction to a share of the host's access-link capacity.
"""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

import networkx as nx

from cybertwin.ai.actions import Action
from cybertwin.lab.addressing import build_addressing
from cybertwin.model import Network, build_network

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_IFACE = re.compile(r"^eth[0-9]{1,3}$")


def _check_name(n: str) -> str:
    if not _NAME.match(n):
        raise ValueError(f"unsafe node name {n!r}")
    return n


def _default_runner(argv: list[str]) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15).stdout


class Actuator:
    def __init__(self, raw: dict, dry_run: bool = True, audit_path: str | Path | None = None,
                 runner: Callable[[list[str]], str] | None = None):
        self.lab = raw.get("name", "cybertwin")
        self.addr = build_addressing(raw)
        self.net: Network = build_network(raw)
        self.dry_run = dry_run
        self.audit_path = Path(audit_path) if audit_path else None
        self.runner = runner or _default_runner
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    # -- helpers -------------------------------------------------------------------
    def _exec(self, node: str, *cmd: str) -> list[str]:
        return ["docker", "exec", f"clab-{self.lab}-{_check_name(node)}", *cmd]

    def _nearest_router(self, host: str) -> str:
        dist = nx.single_source_shortest_path_length(self.net.graph, host)
        routers = [(d, n) for n, d in dist.items() if self.net.graph.nodes[n]["role"] == "router"]
        if not routers:
            raise ValueError(f"no router reachable from {host}")
        return min(routers)[1]

    def _ip(self, node: str) -> str:
        return str(ipaddress.ip_address(self.addr["primary"][node]))

    # -- planning ---------------------------------------------------------------------
    def plan(self, a: Action) -> dict:
        apply: list[list[str]] = []
        undo: list[list[str]] = []
        g = self.net.graph
        if a.kind == "no_op":
            pass
        elif a.kind == "isolate_host":
            ip, r = self._ip(a.target), self._nearest_router(a.target)
            for flag in ("-s", "-d"):
                apply.append(self._exec(r, "iptables", "-I", "FORWARD", "1", flag, ip, "-j", "DROP"))
                undo.append(self._exec(r, "iptables", "-D", "FORWARD", flag, ip, "-j", "DROP"))
        elif a.kind == "rate_limit_host":
            peer = next(iter(g.neighbors(a.target)))
            iface = self.addr["ifaces"][a.target][peer]
            assert _IFACE.match(iface)
            rate = max(1, int(g.edges[a.target, peer]["cap_mbps"] * a.param))
            apply.append(self._exec(a.target, "tc", "qdisc", "replace", "dev", iface, "root", "tbf",
                                    "rate", f"{rate}mbit", "burst", "32kbit", "latency", "400ms"))
            undo.append(self._exec(a.target, "tc", "qdisc", "del", "dev", iface, "root"))
        elif a.kind == "isolate_segment":
            apply.append(self._exec(a.target, "ip", "link", "set", "br0", "down"))
            undo.append(self._exec(a.target, "ip", "link", "set", "br0", "up"))
        elif a.kind == "reroute_avoid_link":
            x, y = a.target.split("|")
            cost = int(10 * (a.param or 10.0))
            for node, peer in ((x, y), (y, x)):
                if g.nodes[node]["role"] != "router":
                    continue
                iface = self.addr["ifaces"][node][peer]
                for word, bag in ((f"ip ospf cost {cost}", apply), ("no ip ospf cost", undo)):
                    bag.append(self._exec(node, "vtysh", "-c", "configure terminal",
                                          "-c", f"interface {iface}", "-c", word))
        else:
            raise ValueError(f"unknown action kind {a.kind!r}")
        return {"apply": apply, "rollback": undo}

    # -- execution ---------------------------------------------------------------------
    def execute(self, a: Action, reason: str = "") -> dict:
        plan = self.plan(a)
        rec = {"ts": time.time(), "action": a.label, "reason": reason, "dry_run": self.dry_run,
               "apply": plan["apply"], "rollback": plan["rollback"], "status": "planned"}
        if not self.dry_run:
            done = 0
            try:
                for argv in plan["apply"]:
                    self.runner(argv)
                    done += 1
                rec["status"] = "applied"
            except Exception as exc:
                # apply[i] <-> rollback[i]. Undo everything that succeeded PLUS the command that
                # failed (it may have taken partial effect); undo errors are swallowed on purpose.
                for argv in reversed(plan["rollback"][:done + 1]):
                    try:
                        self.runner(argv)
                    except Exception:
                        pass
                rec["status"] = f"failed+rolled_back: {exc}"
        self._audit(rec)
        return rec

    def rollback(self, rec: dict) -> dict:
        out = {"ts": time.time(), "action": rec["action"], "status": "rollback_planned", "rollback": rec["rollback"]}
        if not self.dry_run:
            for argv in rec["rollback"]:
                self.runner(argv)
            out["status"] = "rolled_back"
        self._audit(out)
        return out

    def _audit(self, rec: dict) -> None:
        if self.audit_path:
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
