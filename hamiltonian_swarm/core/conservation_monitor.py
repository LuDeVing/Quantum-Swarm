"""
Real-time energy conservation monitor.

Tracks a sliding window of Hamiltonian values H(t) and detects:
  - Energy drift: (max - min) / mean over the window
  - Statistical anomalies: readings > z_score_threshold * σ from mean
"""

from __future__ import annotations
import logging
from collections import deque
from typing import Callable, Deque, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class ConservationMonitor:
    """
    Sliding-window energy conservation monitor.

    Parameters
    ----------
    window_size : int
        Number of recent H readings to retain.
    drift_threshold : float
        Maximum allowed (max-min)/mean drift ratio.
    z_score_threshold : float
        Z-score above which a reading is flagged as an anomaly.
    reset_callback : callable, optional
        Function called when energy drift exceeds the critical threshold.
    """

    def __init__(
        self,
        window_size: int = 200,
        drift_threshold: float = 0.05,
        z_score_threshold: float = 3.0,
        reset_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.window_size = window_size
        self.drift_threshold = drift_threshold
        self.z_score_threshold = z_score_threshold
        self.reset_callback = reset_callback

        self._window: Deque[float] = deque(maxlen=window_size)
        self.total_anomalies: int = 0
        self.mean_drift: float = 0.0
        self.max_spike: float = 0.0
        self._drift_history: List[float] = []

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def record(self, H_value: float) -> None:
        """
        Record a new energy reading.

        Automatically checks for anomalies and fires reset_callback if
        drift exceeds the critical threshold.

        Parameters
        ----------
        H_value : float
            Current Hamiltonian value H(q, p).
        """
        self._window.append(H_value)

        if len(self._window) < 2:
            return

        drift = self.energy_drift_score()
        self._drift_history.append(drift)
        self.mean_drift = float(np.mean(self._drift_history[-100:]))

        if H_value > self.max_spike:
            self.max_spike = H_value

        # Anomaly detection
        if self.detect_anomaly(self.z_score_threshold):
            self.total_anomalies += 1
            logger.warning(
                "Energy anomaly detected! H=%.6f, total_anomalies=%d",
                H_value,
                self.total_anomalies,
            )

        # Drift threshold trigger
        if drift > self.drift_threshold:
            logger.warning(
                "Energy drift %.4f exceeds threshold %.4f — firing reset callback.",
                drift,
                self.drift_threshold,
            )
            if self.reset_callback is not None:
                self.reset_callback()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def energy_drift_score(self) -> float:
        """
        Compute (max(H) - min(H)) / |mean(H)| over the current window.

        Returns
        -------
        float
            Drift score. 0 = perfectly conserved.
        """
        if len(self._window) < 2:
            return 0.0
        arr = np.array(list(self._window))
        mean_H = np.mean(arr)
        if abs(mean_H) < 1e-12:
            return 0.0
        return float((arr.max() - arr.min()) / abs(mean_H))

    def is_stable(self, threshold: Optional[float] = None) -> bool:
        """
        Return True if the current drift score is below the threshold.

        Parameters
        ----------
        threshold : float, optional
            Override the instance drift_threshold.

        Returns
        -------
        bool
        """
        thr = threshold if threshold is not None else self.drift_threshold
        return self.energy_drift_score() < thr

    def detect_anomaly(self, z_score_threshold: Optional[float] = None) -> bool:
        """
        Return True if the most recent reading is > z_score_threshold * σ
        from the window mean.

        Parameters
        ----------
        z_score_threshold : float, optional
            Override instance threshold.

        Returns
        -------
        bool
        """
        if len(self._window) < 3:
            return False
        z_thr = z_score_threshold if z_score_threshold is not None else self.z_score_threshold
        arr = np.array(list(self._window))
        mean = arr.mean()
        std = arr.std()
        if std < 1e-12:
            return False
        z = abs(arr[-1] - mean) / std
        return bool(z > z_thr)

    # ------------------------------------------------------------------
    # State summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a summary dict of monitor statistics."""
        return {
            "window_size": len(self._window),
            "drift_score": self.energy_drift_score(),
            "is_stable": self.is_stable(),
            "total_anomalies": self.total_anomalies,
            "mean_drift": self.mean_drift,
            "max_spike": self.max_spike,
        }

    def reset(self) -> None:
        """Clear the sliding window and reset counters."""
        self._window.clear()
        self.total_anomalies = 0
        self.mean_drift = 0.0
        self.max_spike = 0.0
        self._drift_history.clear()
        logger.info("ConservationMonitor reset.")
