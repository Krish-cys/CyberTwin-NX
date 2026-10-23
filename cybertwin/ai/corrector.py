"""Learned residual correction for the simulator.

The flow simulator is analytic; its configured delays never match a real network exactly.
We fit observed = a * predicted + b on warm-up (predicted, observed) latency pairs and
apply it to later predictions. This is the 'learned' part of the twin: small, inspectable,
and easy to compare against the uncorrected simulator.
"""
from __future__ import annotations

import numpy as np


class Calibrator:
    def __init__(self):
        self.a = 1.0
        self.b = 0.0
        self.fitted = False

    def fit(self, predicted, observed) -> "Calibrator":
        x = np.asarray(predicted, dtype=float)
        y = np.asarray(observed, dtype=float)
        if len(x) >= 3 and np.ptp(x) > 1e-9:
            self.a, self.b = (float(v) for v in np.polyfit(x, y, 1))
            self.fitted = True
        return self

    def __call__(self, x: float) -> float:
        return self.a * x + self.b
