# Evaluation protocol

Goal: show (1) the twin predicts reality well enough to rank responses, (2) the AI loop beats simple baselines,
(3) the safety gate prevents harm when the twin is wrong. Fix seeds and report mean ± std over ≥ 20 runs.

## Metrics

| Group | Metric | Definition |
|---|---|---|
| Fidelity | Latency MAPE | `mean(|pred − obs| / obs)` over reachable flows (`verify/fidelity.compare`) |
| Fidelity | Loss MAE, util MAE | absolute error of per-flow loss / per-link utilisation |
| Fidelity | Reachability accuracy | share of flows where twin and network agree on reachable/unreachable |
| Fidelity | Decision agreement | does the twin's *ranking* of candidate actions match the ranking measured on the real network? (Kendall τ) |
| Detection | Time to detect, false alarms / hour | ticks from injection to debounced alert; alerts during clean traffic |
| Response | Time to remediate | injection → exfil < 5 % of offered |
| Response | Collateral damage | priority-weighted loss of non-suspect legitimate traffic (`summarize(exclude_src=…)`) |
| Response | Residual risk | attack-graph risk after the action ÷ risk before |
| Safety | Harmful-if-applied rate | share of top-ranked candidates that, applied blindly, cause > 15 % service loss on the real network |
| Safety | Gate catch rate | share of those caught (BLOCKED/ESCALATE) |

## Baselines

1. **No action** (lower bound).
2. **Fixed playbook**: always isolate the flagged host; no simulation, no gate.
3. **Twin without calibration** (ablation of the learned corrector).
4. **Twin without gate** (ablation of the safety layer).

## Experiments

| # | Experiment | Procedure | Expected evidence |
|---|---|---|---|
| E1 | Steady-state fidelity | 30 min baseline traffic on Containerlab; log `compare()` every tick | MAPE, loss/util MAE with and without calibration |
| E2 | Failure what-ifs | Fail r2–r3, then r2; compare twin prediction (made *before* the failure) with measured outcome | Reachability accuracy, latency error after reroute |
| E3 | Surge what-ifs | Scale traffic ×2/×3/×4 | Predicted congested links vs measured |
| E4 | Compromise response | `traffic attack` from each host in turn (n ≥ 20 runs) | Detection delay, remediation time, collateral, residual risk vs baselines |
| E5 | Lateral movement | Compare attack-graph exposure ranking with a scripted multi-hop scenario | Rank agreement of predicted exposed hosts |
| E6 | Twin-is-wrong stress | Inject unmodelled behaviour (extra background load, a hidden link) so fidelity degrades | Gate escalations rise; harmful-if-applied rate with vs without gate |
| E7 | Drift | Stop telemetry for N ticks, then resume | Time for fidelity to recover |

## Honest-failure analysis (required section in the report)

For each of ≥ 3 cases where the twin was wrong, record: what was predicted, what happened, root cause
(model simplification, stale telemetry, wrong parameter, unmodelled behaviour), and whether the gate caught it.

## Threats to validity

* Emulated network ≠ production; state which behaviours Containerlab/FRR do not reproduce.
* Attack-graph probabilities are assumptions; run a sensitivity sweep (±50 %).
* Synthetic-emulator results validate plumbing only and must not be reported as fidelity.
