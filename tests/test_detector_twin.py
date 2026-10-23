import numpy as np

from cybertwin.ai.corrector import Calibrator
from cybertwin.ai.detector import HostAnomalyDetector
from cybertwin.model import build_network
from cybertwin.telemetry.synthetic import SyntheticEmulator
from cybertwin.twin.state import TwinState
from cybertwin.verify.fidelity import compare


def _warm(net, n=60, seed=0):
    emu = SyntheticEmulator(net, seed=seed)
    twin = TwinState(net)
    feats, pairs = [], []
    for _ in range(n):
        tel = emu.tick()
        twin.sync(tel)
        twin.mark_baseline(tel)
        feats.extend(tel.host_feats.values())
        pairs.extend(twin.latency_pairs(tel))
    return emu, twin, np.array(feats), pairs


def test_detector_flags_compromise_but_not_clean_hosts(net):
    emu, twin, feats, _ = _warm(net)
    det = HostAnomalyDetector().fit(feats)
    clean_flags = sum(bool(det.flag(emu.tick().host_feats)) for _ in range(30))
    assert clean_flags <= 1
    emu.inject("compromise", host="h2")
    flagged = det.flag(emu.tick().host_feats)
    assert set(flagged) == {"h2"}


def test_calibration_reduces_latency_error(net):
    emu, twin, _, pairs = _warm(net)
    twin.calib.fit(*zip(*pairs))
    tel = emu.tick()
    twin.sync(tel)
    raw_err = compare(twin.predict(), tel)["latency_mape"]
    cal_err = compare(twin.predict(), tel, twin.calib)["latency_mape"]
    assert twin.calib.fitted and cal_err < raw_err


def test_calibrator_is_identity_without_data():
    c = Calibrator().fit([1.0], [2.0])
    assert c(5.0) == 5.0 and not c.fitted


def test_twin_tracks_link_failure_from_telemetry(net):
    emu, twin, _, _ = _warm(net, n=5)
    emu.inject("link_failure", a="r2", b="r3")
    tel = emu.tick()
    twin.sync(tel)
    assert twin.net.graph.edges["r2", "r3"]["up"] is False
    m = compare(twin.predict(), tel)
    assert m["reach_acc"] == 1.0                   # twin agrees with reality on who can reach whom


def test_incident_net_tags_only_new_flows_from_the_suspect(net):
    emu, twin, _, _ = _warm(net, n=5)
    emu.inject("compromise", host="h2", target="srv2")
    twin.sync(emu.tick())
    inc = twin.incident_net("h2")
    mal = {d.name for d in inc.demands if d.malicious}
    assert mal == {"exfil:h2>srv2"}
    assert not any(d.malicious for d in twin.net.demands)       # original twin untouched
