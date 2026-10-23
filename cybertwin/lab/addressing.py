"""Deterministic interface + IP plan derived from data/topology.yaml.

Used by BOTH the Containerlab generator and the actuator, so the commands the actuator
sends always match the lab that was generated.

Plan
  * each switch is one /24 segment (10.1.<n>.0/24); its single router takes .1, endpoints .10+
  * every other link is a /30 point-to-point (10.255.<n>.0/30): a gets .1, b gets .2
  * interfaces are named eth1.. per node, in topology link order (eth0 is the management NIC)
"""
from __future__ import annotations

import ipaddress


def build_addressing(raw: dict) -> dict:
    nodes, links = raw["nodes"], raw["links"]
    ifaces: dict = {n: {} for n in nodes}
    count = {n: 0 for n in nodes}
    for l in links:
        a, b = l["a"], l["b"]
        count[a] += 1
        count[b] += 1
        ifaces[a][b] = f"eth{count[a]}"
        ifaces[b][a] = f"eth{count[b]}"

    ips: dict = {n: {} for n in nodes}
    gateways: dict = {}
    seg = 0
    for sw, attrs in nodes.items():
        if attrs["role"] != "switch":
            continue
        seg += 1
        subnet = ipaddress.ip_network(f"10.1.{seg}.0/24")
        peers = list(ifaces[sw])
        routers = [p for p in peers if nodes[p]["role"] == "router"]
        if len(routers) != 1:
            raise ValueError(f"switch {sw} must attach to exactly one router (found {routers})")
        gw = subnet.network_address + 1
        ips[routers[0]][ifaces[routers[0]][sw]] = f"{gw}/24"
        nxt = 10
        for peer in peers:
            if peer == routers[0]:
                continue
            ips[peer][ifaces[peer][sw]] = f"{subnet.network_address + nxt}/24"
            gateways[peer] = str(gw)
            nxt += 1

    p2p = 0
    for l in links:
        a, b = l["a"], l["b"]
        if "switch" in (nodes[a]["role"], nodes[b]["role"]):
            continue
        p2p += 1
        subnet = ipaddress.ip_network(f"10.255.{p2p}.0/30")
        ips[a][ifaces[a][b]] = f"{subnet.network_address + 1}/30"
        ips[b][ifaces[b][a]] = f"{subnet.network_address + 2}/30"
        for end, other in ((a, b), (b, a)):
            if nodes[end]["role"] in ("host", "server") and nodes[other]["role"] == "router":
                gateways[end] = str(ipaddress.ip_interface(ips[other][ifaces[other][end]]).ip)

    primary = {n: next(iter(sorted(ips[n].values())), None) for n in nodes if nodes[n]["role"] in ("host", "server")}
    primary = {n: ip.split("/")[0] for n, ip in primary.items() if ip}
    return {"ifaces": ifaces, "ips": ips, "gateways": gateways, "primary": primary}
