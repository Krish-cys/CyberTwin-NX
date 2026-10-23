"""Traffic + 'compromised host' emulation for the Containerlab testbed.

Everything here runs against YOUR OWN lab containers only, as `docker exec` argv lists:
  start   : iperf3 servers on every destination + one UDP client per demand at its offered load
  stop    : kill all iperf3 in the lab
  attack  : emulate a compromised host -- a bulk UDP transfer to `--target` (exfil-like volume)
            plus a ping sweep (nmap -sn) of the host's OWN /24 segment (fan-out signal)

Use --dry-run to print the commands without running them.
"""
from __future__ import annotations

import ipaddress
import subprocess

from cybertwin.lab.addressing import build_addressing

ATTACK_PORT = 5999


def _x(lab: str, node: str, *cmd: str, detach: bool = False) -> list[str]:
    return ["docker", "exec", *(["-d"] if detach else []), f"clab-{lab}-{node}", *cmd]


def plan_start(raw: dict) -> list[list[str]]:
    lab, addr = raw.get("name", "cybertwin"), build_addressing(raw)
    cmds: list[list[str]] = []
    flows = list(enumerate(raw.get("demands", [])))
    for i, d in flows:
        cmds.append(_x(lab, d["dst"], "iperf3", "-s", "-D", "-p", str(5201 + i)))
    for i, d in flows:
        cmds.append(_x(lab, d["src"], "iperf3", "-c", addr["primary"][d["dst"]], "-p", str(5201 + i),
                       "-u", "-b", f"{float(d['mbps']):g}M", "-t", "86400", detach=True))
    return cmds


def plan_stop(raw: dict) -> list[list[str]]:
    lab = raw.get("name", "cybertwin")
    return [_x(lab, n, "pkill", "iperf3") for n, a in raw["nodes"].items() if a["role"] in ("host", "server")]


def plan_attack(raw: dict, host: str, target: str, mbps: float = 120.0) -> list[list[str]]:
    lab, addr = raw.get("name", "cybertwin"), build_addressing(raw)
    if raw["nodes"].get(host, {}).get("role") != "host" or target not in addr["primary"]:
        raise ValueError("host must be a lab host and target a lab host/server")
    segment = ipaddress.ip_interface(sorted(addr["ips"][host].values())[0]).network
    return [
        _x(lab, target, "iperf3", "-s", "-D", "-p", str(ATTACK_PORT)),
        _x(lab, host, "iperf3", "-c", addr["primary"][target], "-p", str(ATTACK_PORT),
           "-u", "-b", f"{mbps:g}M", "-t", "600", detach=True),
        _x(lab, host, "nmap", "-sn", str(segment), detach=True),
    ]


def run(cmds: list[list[str]], dry_run: bool = False) -> None:
    for argv in cmds:
        print("$", " ".join(argv))
        if not dry_run:
            subprocess.run(argv, check=False, timeout=30)
