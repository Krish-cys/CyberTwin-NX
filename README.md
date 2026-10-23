# CyberTwin-NX

An AI-assisted **network digital twin**. It mirrors a network from telemetry, simulates "what if?" scenarios
(link/router failure, traffic surge, host compromise, lateral movement), and tests candidate responses
**inside the twin** before anything touches the real network.

```
 REAL / EMULATED NETWORK ── telemetry ──► TWIN STATE (NetworkX graph + offered load)
        ▲                                        │
        │ approved action                        ▼
   ACTUATOR (dry-run, rollback, audit)     DETECTOR (Isolation Forest) ── suspect host
        ▲                                        │
   SAFETY GATE ◄── ranked outcomes ◄── SIMULATOR (flow model) ◄── candidate actions
        │
        └──► VERIFY: predicted vs observed → fidelity log
```

## Quick start

```bash
pip install -r requirements.txt
python -m pytest -q                                   # 52 tests
python -m cybertwin demo                              # full loop on the synthetic emulator
python -m cybertwin whatif link_failure --arg a=r2 --arg b=r3
python -m cybertwin whatif compromise  --arg host=h2
```

The demo: warm-up → calibrate twin + train detector → quiet period (false-alarm count) → `h2` is compromised
and starts exfiltrating → detector fires → 5 candidate responses are simulated and scored → the safety gate
reviews them → the best approved action is applied (dry-run command plan printed) → predicted vs observed
outcome is compared.

## Web dashboard

```bash
python -m cybertwin ui --open          # http://127.0.0.1:8765  (or: make ui)
```

Four views, dark "network ops" theme with a light-mode toggle, no extra dependencies (stdlib server + vanilla JS):

| View | What it does |
|---|---|
| **Network Map** | Live topology: link utilisation colours, animated traffic, node details, offered flows |
| **What-If Lab** | Link/router failure, traffic surge, host compromise: before/after map, KPI deltas, per-flow impact, lateral-movement exposure |
| **Incident Response** | Launch an attack and watch detect, simulate candidates, safety gate, dry-run command plan, verify (anomaly chart + timeline) |
| **Audit & Fidelity** | Latency-error chart (raw vs calibrated), predicted-vs-actual table, action audit trail from `data/runs/` |

The UI is **dry-run only**: it plans commands and logs them, it never executes anything. It has no authentication and
binds to `127.0.0.1` by default; do not expose it to an untrusted network.

## Real testbed (Containerlab)

```bash
python -m cybertwin gen-lab                  # lab/cybertwin.clab.yml + FRR configs from data/topology.yaml
sudo containerlab deploy -t lab/cybertwin.clab.yml
python -m cybertwin traffic start            # baseline iperf3 load  (add --dry-run to preview)
python -m cybertwin traffic attack --host h2 --target srv2    # emulate a compromised host
```

Then swap `SyntheticEmulator` for `ContainerlabCollector` (`telemetry/containerlab.py`) in `main.py`
and set `Actuator(dry_run=False)` once you trust the gate.

## What is real, what is not (read this)

| Part | Status |
|---|---|
| Flow simulator, scenarios, attack-graph risk, scorer, gate, actuator planning/rollback, lab generator | Implemented and unit-tested (39 tests) |
| Detector + calibrator | Implemented; evaluated only on **synthetic** data |
| `SyntheticEmulator` | Stand-in for the real network. It **reuses the twin's flow model** with hidden parameters, so fidelity numbers from it validate plumbing, not real-world accuracy |
| Generated Containerlab files | Consistency-tested (unique IPs, matching interfaces); **never deployed** from this repo |
| `ContainerlabCollector` | **Experimental, untested** against a live lab; `failed_auth` and firewall/tc state are TODO |
| Dashboard / UI | Implemented (`cybertwin/ui`), covered by API/server tests; visually checked in headless Chromium only |
| Attack-graph probabilities | Assumptions in `data/topology.yaml`, not measurements |

## Known limitations

* Links are undirected (both directions share one capacity) → congestion is over-estimated on full-duplex links.
* The flow model has no TCP dynamics, queue buffers or ECMP; use it for relative ranking, not absolute prediction.
* `isolate_host` is enforced at the first-hop router, so traffic inside one L2 segment is not blocked.
* Single-attacker, single-incident logic; concurrent incidents are not handled.
* Collateral damage deliberately excludes the suspect's own traffic (it is untrusted); change `exclude_src` if you disagree.

## Layout

```
data/topology.yaml        single source of truth (nodes, links, demands, attack edges)
cybertwin/model.py        Network / Demand dataclasses, topology loader + validation
cybertwin/sim/flow.py     flow-level simulator (routing, load, latency, loss)
cybertwin/scenarios/      what-ifs (whatif.py) and lateral-movement attack graph (lateral.py)
cybertwin/twin/state.py   twin: sync from telemetry, predict, incident view
cybertwin/telemetry/      schema, synthetic emulator, Containerlab collector
cybertwin/ai/             detector, calibrator (learned), candidate actions, scorer
cybertwin/safety/gate.py  allowlist, protected assets, collateral cap, fidelity check
cybertwin/actuator/       action -> argv commands, dry-run, rollback, audit log
cybertwin/verify/         predicted-vs-observed metrics, fidelity log
cybertwin/lab/            addressing plan, Containerlab generator, traffic/attack emulation
cybertwin/main.py         the end-to-end loop
tests/                    39 tests
docs/EVALUATION.md        experiment protocol for the report
```

## Roadmap (suggested order)

1. Run the loop against a real Containerlab deployment; replace the synthetic emulator.
2. Directional links + simple queue/TCP model; re-measure fidelity.
3. Failure/surge scenarios in the decision loop (candidate generators for non-security incidents).
4. Dashboard (FastAPI + a topology view) reading `data/runs/*.jsonl`.
5. Optional: reinforcement-learning action selection trained inside the twin.
