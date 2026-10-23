"""End-to-end loop: observe -> sync -> detect -> simulate candidates -> gate -> act -> verify."""
from __future__ import annotations

import numpy as np

from cybertwin.actuator.actuator import Actuator
from cybertwin.ai.actions import generate_candidates
from cybertwin.ai.detector import HostAnomalyDetector
from cybertwin.ai.scorer import rank
from cybertwin.model import build_network, load_raw
from cybertwin.safety.gate import review
from cybertwin.scenarios.whatif import run_whatif
from cybertwin.sim.flow import simulate
from cybertwin.telemetry.synthetic import SyntheticEmulator
from cybertwin.twin.state import TwinState
from cybertwin.verify.fidelity import FidelityLog, compare, observed_summary

WARMUP_TICKS = 60
QUIET_TICKS = 15
DEBOUNCE = 2


def run_demo(seed: int = 0, verbose: bool = True, audit_path=None, fidelity_path=None,
             attacker: str = "h2") -> dict:
    say = print if verbose else (lambda *a, **k: None)
    raw = load_raw()
    emu = SyntheticEmulator(build_network(raw), seed=seed)
    twin = TwinState(build_network(raw))
    flog = FidelityLog(fidelity_path)
    actuator = Actuator(raw, dry_run=True, audit_path=audit_path)

    # 1. warm-up: learn the baseline, fit the detector and the calibrator ---------------
    feats, pairs = [], []
    for _ in range(WARMUP_TICKS):
        tel = emu.tick()
        twin.sync(tel)
        twin.mark_baseline(tel)
        feats.extend(tel.host_feats.values())
        pairs.extend(twin.latency_pairs(tel))
    twin.calib.fit(*zip(*pairs))
    detector = HostAnomalyDetector().fit(np.array(feats))
    say(f"[warm-up] {WARMUP_TICKS} ticks, calibration: observed = {twin.calib.a:.3f} * predicted + {twin.calib.b:.3f}")

    streak: dict = {}

    def monitor():
        tel = emu.tick()
        twin.sync(tel)
        pred = twin.predict()
        flog.write(phase="monitor", t=tel.t, raw=compare(pred, tel), calibrated=compare(pred, tel, twin.calib))
        flagged = detector.flag(tel.host_feats)
        for h in list(streak):
            if h not in flagged:
                streak[h] = 0
        for h in flagged:
            streak[h] = streak.get(h, 0) + 1
        return tel, sorted(h for h, c in streak.items() if c >= DEBOUNCE)

    # 2. quiet period: count false alarms ----------------------------------------------------
    false_alarms = sum(1 for _ in range(QUIET_TICKS) if monitor()[1])
    say(f"[monitor] {QUIET_TICKS} quiet ticks, false alarms: {false_alarms}")

    # 3. attack ------------------------------------------------------------------------------
    emu.inject("compromise", host=attacker, exfil_mbps=120.0, target="srv2")
    say(f"[attack ] {attacker} compromised (exfil -> srv2 started)")
    suspects, delay = [], 0
    for delay in range(1, 11):
        tel, suspects = monitor()
        if suspects:
            break
    if not suspects:
        return {"detected": None, "false_alarms": false_alarms}
    suspect = suspects[0]
    say(f"[detect ] {suspect} flagged after {delay} tick(s)")

    # 4. what-if every candidate response inside the twin ----------------------------------
    incident = twin.incident_net(suspect)
    candidates = generate_candidates(incident, suspect, simulate(incident, twin.params))
    ranked = rank(incident, candidates, suspect, twin.params)
    no_op = next(e for e in ranked if e.action.kind == "no_op")
    fid = compare(twin.predict(), twin.last_tel, twin.calib)["latency_mape"]

    say("\n  candidate action                         svc_loss  exfil   risk   cost   total   gate")
    chosen, decision, escalations = None, None, []
    for e in ranked:
        d = review(e, no_op, incident, fid)
        c = e.components
        say(f"  {e.action.label:<40} {c['service_loss']:7.1%} {c['exfil']:7.1%} {c['risk']:6.2f} "
            f"{c['cost']:5.2f} {e.total:7.3f}   {d.verdict}" + (f" ({'; '.join(d.reasons)})" if d.reasons and not d.approved else ""))
        if d.approved and chosen is None:
            chosen, decision = e, d
        elif not d.approved and chosen is None:
            escalations.append((e.action.label, d.verdict, d.reasons))
    say("")
    if chosen is None or chosen.action.kind == "no_op":
        return {"detected": suspect, "chosen": "no_op", "false_alarms": false_alarms}

    # 5. act (dry-run) and apply to the emulated network ----------------------------------
    rec = actuator.execute(chosen.action, reason=f"detected {suspect}; best gated action")
    emu.apply_action(chosen.action)
    say(f"[act    ] {chosen.action.label} -> {len(rec['apply'])} command(s), dry-run")
    for argv in rec["apply"]:
        say("          $ " + " ".join(argv))

    # 6. verify: did reality match the prediction? ---------------------------------------------
    obs = []
    for _ in range(3):
        tel = emu.tick()
        twin.sync(tel)
        obs.append(observed_summary(tel, twin.baseline_flows, exclude_src=suspect))
    actual = {k: float(np.mean([o[k] for o in obs])) for k in ("service_loss", "exfil")}
    predicted = {k: chosen.components[k] for k in ("service_loss", "exfil")}
    pred_after = twin.predict()
    fid_after = compare(pred_after, tel, twin.calib)
    flog.write(phase="verify", action=chosen.action.label, predicted=predicted, actual=actual, fidelity=fid_after)
    say(f"[verify ] predicted {predicted}  actual {actual}")
    say(f"[verify ] post-action latency MAPE (calibrated): {fid_after['latency_mape']:.1%}")

    return {
        "detected": suspect, "detection_delay_ticks": delay, "false_alarms": false_alarms,
        "chosen": chosen.action.label, "decision": decision.verdict,
        "escalated_or_blocked": escalations, "predicted": predicted, "actual": actual,
        "latency_mape_raw": flog.rows[-2]["raw"]["latency_mape"] if len(flog.rows) >= 2 else None,
        "latency_mape_calibrated": fid_after["latency_mape"],
    }


def whatif_cli(scenario: str, kv: dict) -> dict:
    net = build_network(load_raw())
    return run_whatif(net, scenario, **kv)
