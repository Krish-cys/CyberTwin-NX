"""JSON-friendly service layer for the dashboard. Pure functions; no HTTP in here.

The incident runner mirrors cybertwin.main.run_demo step for step (same components, same
thresholds) but records structured events, per-tick series and map snapshots for the UI.
The UI is ALWAYS dry-run: commands are planned and logged, never executed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from cybertwin.actuator.actuator import Actuator
from cybertwin.ai.actions import generate_candidates
from cybertwin.ai.detector import HostAnomalyDetector
from cybertwin.ai.scorer import rank
from cybertwin.main import DEBOUNCE, QUIET_TICKS, WARMUP_TICKS
from cybertwin.model import Network, build_network, load_raw
from cybertwin.safety.gate import review
from cybertwin.scenarios.whatif import SCENARIOS
from cybertwin.scenarios.lateral import compromise_probs, residual_risk
from cybertwin.sim.flow import SimResult, simulate, summarize
from cybertwin.telemetry.synthetic import SyntheticEmulator
from cybertwin.twin.state import TwinState
from cybertwin.verify.fidelity import FidelityLog, compare, observed_summary

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "data" / "runs"
MAX_HISTORY = 400


class InputError(ValueError):
    """Bad request from the browser (reported as HTTP 400)."""


def _lk(a: str, b: str) -> str:
    a, b = sorted((a, b))
    return f"{a}|{b}"


# ---------------------------------------------------------------- views --------------------
def network_view(net: Network, util: dict | None = None, link_up: dict | None = None) -> dict:
    g = net.graph
    nodes = [{"id": n, "role": d["role"], "zone": d.get("zone"), "value": d.get("value", 0),
              "up": bool(d.get("up", True)), "isolated": bool(d.get("isolated", False)),
              "compromised": bool(d.get("compromised", False)),
              "rate_limit": float(d.get("rate_limit", 1.0))} for n, d in g.nodes(data=True)]
    links = []
    for a, b, d in g.edges(data=True):
        key = _lk(a, b)
        up = bool(d.get("up", True)) if link_up is None else bool(link_up.get(tuple(sorted((a, b))), d.get("up", True)))
        u = (util or {}).get(tuple(sorted((a, b))), 0.0)
        links.append({"id": key, "a": a, "b": b, "cap": d["cap_mbps"], "lat": d["lat_ms"],
                      "up": up, "penalty": d.get("penalty", 1.0), "util": round(float(u), 4)})
    return {"nodes": nodes, "links": links}


def topology() -> dict:
    net = build_network(load_raw())
    res = simulate(net)
    return {"view": network_view(net, res.util),
            "demands": [{"name": d.name, "src": d.src, "dst": d.dst, "mbps": d.mbps,
                         "app": d.app, "priority": d.priority} for d in net.demands],
            "access": net.access,
            "kpi": _kpi(net, res),
            "scenarios": sorted(SCENARIOS)}


def _kpi(net: Network, res: SimResult, exclude_src: str | None = None) -> dict:
    s = summarize(net, res, exclude_src=exclude_src)
    s["congested_links"] = [_lk(*k) for k in s["congested_links"]]
    s["max_util"] = float(s["max_util"])
    return s


# ---------------------------------------------------------------- what-if --------------------
def _validated_args(net: Network, scenario: str, args: dict) -> dict:
    g = net.graph
    if scenario not in SCENARIOS:
        raise InputError(f"unknown scenario {scenario!r}")

    def node(k, roles=None):
        v = args.get(k)
        if v not in g:
            raise InputError(f"'{k}' must be a node name, got {v!r}")
        if roles and g.nodes[v]["role"] not in roles:
            raise InputError(f"'{k}' must be a {'/'.join(roles)}")
        return v

    def num(k, lo, hi, default):
        try:
            v = float(args.get(k, default))
        except (TypeError, ValueError):
            raise InputError(f"'{k}' must be a number") from None
        if not lo <= v <= hi:
            raise InputError(f"'{k}' must be between {lo} and {hi}")
        return v

    if scenario == "link_failure":
        a, b = node("a"), node("b")
        if not g.has_edge(a, b):
            raise InputError(f"no link between {a} and {b}")
        return {"a": a, "b": b}
    if scenario == "router_failure":
        return {"node": node("node", ("router", "switch"))}
    if scenario == "surge":
        out = {"factor": num("factor", 0.1, 20, 2.0)}
        if args.get("dst"):
            out["dst"] = node("dst")
        return out
    return {"host": node("host", ("host",)), "exfil_mbps": num("exfil_mbps", 0, 2000, 120.0),
            "target": node("target", ("server",))}


def whatif(scenario: str, args: dict) -> dict:
    net = build_network(load_raw())
    kw = _validated_args(net, scenario, args or {})
    after = SCENARIOS[scenario](net, **kw)
    rb, ra = simulate(net), simulate(after)
    flows = []
    for d in net.demands:
        flows.append({"name": d.name, "src": d.src, "dst": d.dst, "mbps": d.mbps, "priority": d.priority,
                      "before": {"ok": bool(rb.reachable.get(d.name)), "lat": rb.latency.get(d.name),
                                 "loss": rb.loss.get(d.name, 1.0), "path": rb.paths.get(d.name, [])},
                      "after": {"ok": bool(ra.reachable.get(d.name)), "lat": ra.latency.get(d.name),
                                "loss": ra.loss.get(d.name, 1.0), "path": ra.paths.get(d.name, [])}})
    out = {"scenario": scenario, "args": kw,
           "before": {"view": network_view(net, rb.util), "kpi": _kpi(net, rb)},
           "after": {"view": network_view(after, ra.util), "kpi": _kpi(after, ra)},
           "flows": flows}
    if scenario == "compromise":
        probs = compromise_probs(after, kw["host"])
        out["lateral"] = {"risk": residual_risk(after, kw["host"]),
                          "exposed": [{"node": k, "p": round(v, 3), "value": after.value(k)}
                                      for k, v in sorted(probs.items(), key=lambda kv: -kv[1]) if k != kw["host"]]}
    return out


# ---------------------------------------------------------------- incident -------------------
def run_incident(seed: int = 0, attacker: str = "h2", log_dir: Path | None = LOG_DIR) -> dict:
    raw = load_raw()
    base = build_network(raw)
    if attacker not in base.hosts():
        raise InputError(f"attacker must be one of {base.hosts()}")
    log_dir = Path(log_dir) if log_dir else None
    emu = SyntheticEmulator(build_network(raw), seed=int(seed))
    twin = TwinState(build_network(raw))
    flog = FidelityLog(log_dir / "fidelity.jsonl" if log_dir else None)
    actuator = Actuator(raw, dry_run=True, audit_path=log_dir / "audit.jsonl" if log_dir else None)
    events, series = [], []

    def view(tel):
        return network_view(emu.net, {tuple(sorted(k)): v for k, v in tel.link_util.items()},
                            {tuple(sorted(k)): v for k, v in tel.link_up.items()})

    # 1. warm-up
    feats, pairs = [], []
    for _ in range(WARMUP_TICKS):
        tel = emu.tick()
        twin.sync(tel)
        twin.mark_baseline(tel)
        feats.extend(tel.host_feats.values())
        pairs.extend(twin.latency_pairs(tel))
    twin.calib.fit(*zip(*pairs))
    detector = HostAnomalyDetector().fit(np.array(feats))
    events.append({"type": "warmup", "ticks": WARMUP_TICKS,
                   "calibration": {"a": twin.calib.a, "b": twin.calib.b},
                   "threshold": detector.threshold, "hosts": base.hosts()})

    streak: dict = {}

    def monitor(phase: str):
        tel = emu.tick()
        twin.sync(tel)
        flog.write(phase="monitor", t=tel.t, raw=compare(twin.predict(), tel),
                   calibrated=compare(twin.predict(), tel, twin.calib))
        scores = detector.scores(tel.host_feats)
        flagged = detector.flag(tel.host_feats)
        for h in list(streak):
            if h not in flagged:
                streak[h] = 0
        for h in flagged:
            streak[h] = streak.get(h, 0) + 1
        series.append({"t": tel.t, "phase": phase, "scores": scores,
                       "max_util": max(tel.link_util.values(), default=0.0)})
        return tel, sorted(h for h, c in streak.items() if c >= DEBOUNCE)

    # 2. quiet period
    false_alarms, tel = 0, None
    for _ in range(QUIET_TICKS):
        tel, s = monitor("quiet")
        false_alarms += bool(s)
    views = {"baseline": view(tel)}
    events.append({"type": "monitor", "ticks": QUIET_TICKS, "false_alarms": false_alarms})

    # 3. attack
    emu.inject("compromise", host=attacker, exfil_mbps=120.0, target="srv2")
    events.append({"type": "attack", "host": attacker, "target": "srv2", "exfil_mbps": 120.0})
    suspects, delay = [], 0
    for delay in range(1, 11):
        tel, suspects = monitor("attack")
        if suspects:
            break
    views["attack"] = view(tel)
    if not suspects:
        events.append({"type": "detect", "host": None, "delay": None})
        return {"events": events, "series": series, "views": views, "meta": _meta(seed, attacker, detector),
                "summary": {"detected": None, "false_alarms": false_alarms}}
    suspect = suspects[0]
    events.append({"type": "detect", "host": suspect, "delay": delay,
                   "score": series[-1]["scores"][suspect]})

    # 4. what-if every candidate inside the twin
    incident = twin.incident_net(suspect)
    candidates = generate_candidates(incident, suspect, simulate(incident, twin.params))
    ranked = rank(incident, candidates, suspect, twin.params)
    no_op = next(e for e in ranked if e.action.kind == "no_op")
    fid = compare(twin.predict(), twin.last_tel, twin.calib)["latency_mape"]
    rows, chosen, decision = [], None, None
    for e in ranked:
        d = review(e, no_op, incident, fid)
        rows.append({"label": e.action.label, "kind": e.action.kind, "target": e.action.target,
                     "components": e.components, "total": e.total, "verdict": d.verdict,
                     "reasons": d.reasons, "chosen": False})
        if d.approved and chosen is None:
            chosen, decision = e, d
            rows[-1]["chosen"] = True
    events.append({"type": "candidates", "rows": rows, "fidelity_mape": fid, "suspect": suspect})
    if chosen is None or chosen.action.kind == "no_op":
        return {"events": events, "series": series, "views": views, "meta": _meta(seed, attacker, detector),
                "summary": {"detected": suspect, "chosen": "no_op", "false_alarms": false_alarms}}

    # 5. act (dry-run)
    rec = actuator.execute(chosen.action, reason=f"detected {suspect}; best gated action (dashboard)")
    emu.apply_action(chosen.action)
    events.append({"type": "act", "action": chosen.action.label, "decision": decision.verdict,
                   "reasons": decision.reasons, "dry_run": True,
                   "commands": [" ".join(c) for c in rec["apply"]],
                   "rollback": [" ".join(c) for c in rec["rollback"]]})

    # 6. verify
    obs = []
    for _ in range(3):
        tel = emu.tick()
        twin.sync(tel)
        obs.append(observed_summary(tel, twin.baseline_flows, exclude_src=suspect))
    views["after"] = view(tel)
    actual = {k: float(np.mean([o[k] for o in obs])) for k in ("service_loss", "exfil")}
    predicted = {k: float(chosen.components[k]) for k in ("service_loss", "exfil")}
    fid_after = compare(twin.predict(), tel, twin.calib)
    flog.write(phase="verify", action=chosen.action.label, predicted=predicted, actual=actual, fidelity=fid_after)
    raw_mape = flog.rows[-2]["raw"]["latency_mape"] if len(flog.rows) >= 2 else None
    events.append({"type": "verify", "predicted": predicted, "actual": actual,
                   "latency_mape_calibrated": fid_after["latency_mape"], "latency_mape_raw": raw_mape,
                   "fidelity": fid_after})
    return {"events": events, "series": series, "views": views, "meta": _meta(seed, attacker, detector),
            "summary": {"detected": suspect, "detection_delay_ticks": delay, "false_alarms": false_alarms,
                        "chosen": chosen.action.label, "decision": decision.verdict,
                        "predicted": predicted, "actual": actual,
                        "latency_mape_raw": raw_mape, "latency_mape_calibrated": fid_after["latency_mape"]}}


def _meta(seed, attacker, detector) -> dict:
    return {"seed": int(seed), "attacker": attacker, "dry_run": True, "threshold": detector.threshold}


# ---------------------------------------------------------------- history --------------------
def _tail_jsonl(path: Path, n: int) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows[-n:]


def history(log_dir: Path = LOG_DIR) -> dict:
    return {"audit": _tail_jsonl(log_dir / "audit.jsonl", 50),
            "fidelity": _tail_jsonl(log_dir / "fidelity.jsonl", MAX_HISTORY)}
