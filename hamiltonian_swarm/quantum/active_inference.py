"""
Active Inference (Free Energy Principle) belief state for agents.

Replaces the Lindblad density matrix with a calibration-free Bayesian model:

    posterior ∝ prior × likelihood

Free Energy F = KL(posterior || prior):
    0.0   = agent fully on-role (posterior == prior)
    rises = agent drifting from expected role behaviour

No γ constants to tune — the role prior IS the restoring force.
Anomaly threshold derived directly from the prior (no empirical calibration):
    F_threshold = -log(prior_healthy / 2)

Anomaly detection strategy:
    1. Rolling z-score: z = (F_last - mean(history)) / std(history) > 2.0
    2. Cold-start fallback (< 5 observations): F > F_threshold
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class ActiveInferenceState:
    """
    Agent belief state as a probability vector evolved via Active Inference.

    The role prior encodes the expected distribution over states
    (healthy / uncertain / confused).  Each observation (combined
    logprob + embedding signal) updates the posterior via Bayesian
    inference.  Free energy = KL(posterior || prior) is the natural
    anomaly signal — zero when the agent is on-role, positive when drifting.

    Parameters
    ----------
    hypotheses : list of str
        Must be ["healthy", "uncertain", "confused"] in that order.
    role_prior : dict[str, float]
        Prior probability for each hypothesis, e.g.
        {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}.
        Values must be positive and will be normalized internally.
    """

    def __init__(
        self,
        hypotheses: List[str],
        role_prior: Dict[str, float],
    ) -> None:
        self.hypotheses = hypotheses
        raw = np.array([role_prior[h] for h in hypotheses], dtype=np.float64)
        self.prior = raw / raw.sum()
        self.probs  = self.prior.copy()
        self._F_history: list[float] = []

        # Cold-start threshold: F > -log(p_healthy / 2)
        # Derivation: if all probability mass shifted to confused,
        # F = log(1/p_confused) ≈ 3.  Half the healthy prior = early-warning level.
        self._F_threshold = float(-np.log(self.prior[0] / 2.0))

        logger.debug(
            "ActiveInferenceState created: hypotheses=%s, prior=%s, F_threshold=%.3f",
            hypotheses, self.prior.tolist(), self._F_threshold,
        )

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, similarities: Dict[str, float]) -> float:
        """
        Bayesian update from cosine similarities to prototype states.

        likelihood[i] = (similarity[i] + 1) / 2  → maps [-1,1] to [0,1]
        posterior     ∝ prior × likelihood
        F             = KL(posterior || prior)

        Parameters
        ----------
        similarities : dict
            Keys match self.hypotheses.  Values in [-1, 1].

        Returns
        -------
        float
            Free energy F after this update.
        """
        likelihoods = np.array(
            [(similarities[h] + 1.0) / 2.0 for h in self.hypotheses],
            dtype=np.float64,
        )
        likelihoods = np.clip(likelihoods, 1e-10, None)

        unnorm = self.prior * likelihoods
        total  = unnorm.sum()
        if total < 1e-10:
            # Degenerate update — keep current state
            return self.free_energy()

        self.probs = unnorm / total
        F = self._kl_from_prior()
        self._F_history.append(F)

        logger.debug(
            "update: healthy=%.3f uncertain=%.3f confused=%.3f  F=%.4f",
            self.probs[0], self.probs[1], self.probs[2], F,
        )
        return F

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def is_anomaly(self) -> bool:
        """
        Return True if this agent's current free energy is anomalously high.

        Strategy
        --------
        1. If ≥ 5 historical observations: z-score > 2.0 relative to own history.
        2. Cold start (< 5 observations): F > F_threshold (prior-derived).
        """
        if not self._F_history:
            return False
        F_last = self._F_history[-1]
        if len(self._F_history) >= 5:
            hist = np.array(self._F_history[:-1])
            z = (F_last - hist.mean()) / (hist.std() + 1e-8)
            return bool(z > 2.0)
        return F_last > self._F_threshold

    # ------------------------------------------------------------------
    # Quantum interference
    # ------------------------------------------------------------------

    @staticmethod
    def interfere_all(states: list[ActiveInferenceState], alpha: float = 0.5) -> None:
        """
        Mean-field quantum interference across a group of agent belief states.

        Converts each agent's posterior probabilities to quantum amplitudes
        (aᵢ = sqrt(pᵢ), Born rule), averages them (mean field), normalises,
        converts back to probabilities, then blends each agent's individual
        posterior with the shared result:

            p_new = (1 - alpha) * p_individual  +  alpha * p_shared

        alpha = 0.0  no interference (agents fully independent)
        alpha = 1.0  full collapse to shared state (agents identical)
        alpha = 0.5  balanced -- individual identity preserved but
                     confused agents pulled toward swarm mean

        After interference each agent records the new F in its history
        so the z-score detector sees the post-interference state.

        Parameters
        ----------
        states : list of ActiveInferenceState
            All agents to interfere together.
        alpha : float
            Blend weight toward shared state. Default 0.5.
        """
        if len(states) < 2:
            return

        # 1. Convert posteriors to amplitudes
        amps = [np.sqrt(np.clip(s.probs, 1e-10, 1.0)) for s in states]

        # 2. Mean-field average
        combined = np.mean(amps, axis=0)
        norm = float(np.linalg.norm(combined))
        if norm < 1e-10:
            return
        combined = combined / norm

        # 3. Convert back to shared probability vector
        shared = combined ** 2
        shared = shared / shared.sum()

        # 4. Blend each agent toward shared state and record new F
        for s in states:
            s.probs = (1.0 - alpha) * s.probs + alpha * shared
            s.probs = s.probs / s.probs.sum()
            F = s._kl_from_prior()
            s._F_history.append(F)

        logger.debug(
            "interfere_all: %d agents  alpha=%.2f  shared=[%.3f, %.3f, %.3f]",
            len(states), alpha, shared[0], shared[1], shared[2],
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def free_energy(self) -> float:
        """KL(posterior || prior) from most recent update.  0 = on-role."""
        return self._F_history[-1] if self._F_history else 0.0

    def entropy(self) -> float:
        """Shannon entropy of posterior.  0 = certain.  log(n) = maximally mixed."""
        p = np.clip(self.probs, 1e-10, 1.0)
        return float(-np.sum(p * np.log(p)))

    def probability(self, i: int) -> float:
        """Posterior probability for hypothesis i."""
        return float(self.probs[i])

    def probabilities(self) -> np.ndarray:
        """Full posterior probability vector."""
        return self.probs.copy()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """
        Reset posterior to prior — agent returns to default role distribution.
        F history is preserved so rolling z-score remains calibrated.
        """
        self.probs = self.prior.copy()
        logger.debug("ActiveInferenceState reset to prior")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _kl_from_prior(self) -> float:
        """KL(posterior || prior) = Σ p log(p/q)."""
        p = np.clip(self.probs,  1e-10, 1.0)
        q = np.clip(self.prior,  1e-10, 1.0)
        return float(np.sum(p * np.log(p / q)))

    def __repr__(self) -> str:
        return (
            f"ActiveInferenceState("
            f"F={self.free_energy():.3f}, "
            f"anomaly={self.is_anomaly()}, "
            f"healthy={self.probability(0):.2f}, "
            f"uncertain={self.probability(1):.2f}, "
            f"confused={self.probability(2):.2f})"
        )
