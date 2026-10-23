import pytest

from cybertwin.main import run_demo


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_full_loop_detects_isolates_and_verifies(seed):
    out = run_demo(seed=seed, verbose=False)
    assert out["detected"] == "h2"
    assert out["false_alarms"] == 0
    assert out["chosen"] == "isolate_host[h2]" and out["decision"] == "APPROVED"
    # reality agrees with the twin: attack traffic stopped, bystanders unharmed
    assert out["actual"]["exfil"] < 0.05
    assert out["actual"]["service_loss"] < 0.05
    assert out["latency_mape_calibrated"] < out["latency_mape_raw"]


def test_loop_works_for_a_different_attacker():
    out = run_demo(seed=3, verbose=False, attacker="h5")
    assert out["detected"] == "h5" and out["chosen"] == "isolate_host[h5]"
