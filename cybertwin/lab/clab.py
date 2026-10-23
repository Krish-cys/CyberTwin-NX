"""Generate a Containerlab topology + FRR configs from data/topology.yaml.

    python -m cybertwin gen-lab            # writes lab/cybertwin.clab.yml and lab/configs/*
    sudo containerlab deploy -t lab/cybertwin.clab.yml

STATUS: generated output is unit-tested for consistency (unique IPs, matching interfaces,
valid YAML) but has NOT been deployed on a live Containerlab host from this repo.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from cybertwin.lab.addressing import build_addressing

FRR_IMAGE = "quay.io/frrouting/frr:10.1.1"
HOST_IMAGE = "wbitt/network-multitool:latest"

DAEMONS = """zebra=yes
bgpd=no
ospfd=yes
ospf6d=no
ripd=no
ripngd=no
isisd=no
pimd=no
ldpd=no
nhrpd=no
eigrpd=no
babeld=no
sharpd=no
pbrd=no
bfdd=no
fabricd=no
vtysh_enable=yes
zebra_options="  -A 127.0.0.1 -s 90000000"
ospfd_options="  -A 127.0.0.1"
"""


def _frr_conf(name: str, idx: int) -> str:
    return (f"frr defaults traditional\nhostname {name}\nlog stdout\n!\n"
            f"router ospf\n ospf router-id 10.0.0.{idx}\n network 10.0.0.0/8 area 0\n!\n")


def render(raw: dict) -> dict[str, str]:
    """Return {relative_path: file_content}."""
    addr = build_addressing(raw)
    nodes = raw["nodes"]
    lab = raw.get("name", "cybertwin")
    files: dict[str, str] = {}
    clab_nodes: dict = {}

    router_idx = 0
    for name, attrs in nodes.items():
        role = attrs["role"]
        ip_cmds = [f"ip addr add {ip} dev {ifc}" for ifc, ip in sorted(addr["ips"][name].items())]
        if role == "router":
            router_idx += 1
            files[f"configs/{name}/frr.conf"] = _frr_conf(name, router_idx)
            files[f"configs/{name}/daemons"] = DAEMONS
            clab_nodes[name] = {
                "kind": "linux", "image": FRR_IMAGE,
                "binds": [f"configs/{name}/daemons:/etc/frr/daemons", f"configs/{name}/frr.conf:/etc/frr/frr.conf"],
                "exec": ["sysctl -w net.ipv4.ip_forward=1"] + ip_cmds,
            }
        elif role == "switch":
            ifs = sorted(addr["ifaces"][name].values())
            clab_nodes[name] = {
                "kind": "linux", "image": HOST_IMAGE,
                "exec": ["ip link add br0 type bridge", "ip link set br0 up"]
                        + [f"ip link set {i} master br0" for i in ifs]
                        + [f"ip link set {i} up" for i in ifs],
            }
        else:  # host / server
            # route the lab's 10.0.0.0/8 via the gateway; keep eth0 (management) default route intact
            clab_nodes[name] = {
                "kind": "linux", "image": HOST_IMAGE,
                "exec": ip_cmds + [f"ip route add 10.0.0.0/8 via {addr['gateways'][name]}"],
            }

    links = [{"endpoints": [f"{l['a']}:{addr['ifaces'][l['a']][l['b']]}",
                            f"{l['b']}:{addr['ifaces'][l['b']][l['a']]}"]} for l in raw["links"]]
    doc = {"name": lab, "topology": {"nodes": clab_nodes, "links": links}}
    files[f"{lab}.clab.yml"] = yaml.safe_dump(doc, sort_keys=False)
    return files


def write(raw: dict, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    written = []
    for rel, content in render(raw).items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(p)
    return written
