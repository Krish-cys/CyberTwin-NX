"""CLI:  python -m cybertwin <demo|whatif|ui|gen-lab|traffic> ..."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cybertwin.lab import traffic
from cybertwin.lab.clab import write as write_lab
from cybertwin.main import run_demo, whatif_cli
from cybertwin.model import load_raw

ROOT = Path(__file__).resolve().parent.parent


def _coerce(v: str):
    try:
        return float(v)
    except ValueError:
        return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cybertwin")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run the full observe->decide->act->verify loop on the synthetic emulator")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--attacker", default="h2")
    d.add_argument("--log-dir", default=str(ROOT / "data" / "runs"))

    w = sub.add_parser("whatif", help="simulate one scenario on the twin")
    w.add_argument("scenario", choices=["link_failure", "router_failure", "surge", "compromise"])
    w.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE",
                   help="scenario argument, e.g. --arg a=r2 --arg b=r3")

    u = sub.add_parser("ui", help="open the web dashboard (dry-run only, stdlib server)")
    u.add_argument("--host", default="127.0.0.1", help="bind address (no auth: keep it local)")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--open", action="store_true", help="open the browser automatically")

    g = sub.add_parser("gen-lab", help="generate the Containerlab topology + FRR configs")
    g.add_argument("--out", default=str(ROOT / "lab"))

    t = sub.add_parser("traffic", help="drive baseline traffic / emulate a compromised host in the lab")
    t.add_argument("action", choices=["start", "stop", "attack"])
    t.add_argument("--host", default="h2")
    t.add_argument("--target", default="srv2")
    t.add_argument("--mbps", type=float, default=120.0)
    t.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "demo":
        log = Path(args.log_dir)
        out = run_demo(seed=args.seed, attacker=args.attacker, audit_path=log / "audit.jsonl",
                       fidelity_path=log / "fidelity.jsonl")
        print("\nSUMMARY", json.dumps(out, indent=2, default=str))
    elif args.cmd == "whatif":
        kv = {k: _coerce(v) for k, v in (a.split("=", 1) for a in args.arg)}
        print(json.dumps(whatif_cli(args.scenario, kv), indent=2, default=str))
    elif args.cmd == "ui":
        from cybertwin.ui.server import serve
        serve(args.host, args.port, args.open)
    elif args.cmd == "traffic":
        raw = load_raw()
        plan = {"start": lambda: traffic.plan_start(raw), "stop": lambda: traffic.plan_stop(raw),
                "attack": lambda: traffic.plan_attack(raw, args.host, args.target, args.mbps)}[args.action]()
        traffic.run(plan, dry_run=args.dry_run)
    else:
        for p in write_lab(load_raw(), args.out):
            print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
