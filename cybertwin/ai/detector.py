"""Host compromise detector: Isolation Forest over per-host behaviour features.

Features (per host, per telemetry window): [out_mbps, distinct_peers (fan-out), failed_auth].
Trained ONLY on warm-up (baseline) windows -- no attack labels needed.
The decision threshold is set just below the lowest training score, and callers should
debounce (require N consecutive windows) before acting.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest


class HostAnomalyDetector:
    def __init__(self, margin: float = 0.02, seed: int = 0):
        self.model = IsolationForest(n_estimators=200, random_state=seed)
        self.margin = margin
        self.threshold = None

    def fit(self, X) -> "HostAnomalyDetector":
        X = np.asarray(X, dtype=float)
        self.model.fit(X)
        self.threshold = float(self.model.score_samples(X).min()) - self.margin
        return self

    def scores(self, host_feats: dict) -> dict:
        hosts = list(host_feats)
        s = self.model.score_samples(np.asarray([host_feats[h] for h in hosts], dtype=float))
        return dict(zip(hosts, map(float, s)))

    def flag(self, host_feats: dict) -> dict:
        """Hosts whose score falls below the threshold -> {host: score}."""
        if self.threshold is None:
            raise RuntimeError("detector is not fitted")
        return {h: s for h, s in self.scores(host_feats).items() if s < self.threshold}
