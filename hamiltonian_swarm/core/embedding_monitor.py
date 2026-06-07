"""
Kalman filter for tracking semantic drift in embedding space.

State vector x = [q, p]:
    q = agent's current output embedding  (position in semantic space)
    p = embedding velocity = q(t) - q(t-1), estimated by the filter

Drift detection via Kalman innovation:
    High z-score  → embedding jumped unexpectedly  (semantic drift)
    Near-zero p   → agent looping / repeating output
    Low z-score   → agent on track

Diagonal covariance is used throughout for O(emb_dim) memory and compute,
which makes this practical for 1536-dim embeddings.
"""

from __future__ import annotations
import logging
from typing import Optional, Tuple

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class EmbeddingKalmanMonitor:
    """
    Kalman filter monitor for semantic position and velocity in embedding space.

    Constant-velocity model:
        q(t+1) = q(t) + p(t)  + w_q    (position advances by velocity)
        p(t+1) = p(t)          + w_p    (velocity changes slowly)
        z(t)   = q(t)          + v      (we observe position directly)

    where w_q, w_p ~ N(0, process_noise * I) and v ~ N(0, observation_noise * I).

    Parameters
    ----------
    emb_dim : int
        Embedding dimensionality (e.g. 1536 for OpenAI, 768 for BERT).
    process_noise : float
        Variance of per-step state noise. Higher = faster adaptation.
    observation_noise : float
        Variance of embedding observation noise. Higher = smoother estimates.
    drift_threshold : float
        Mean innovation z-score above which is_drifting() returns True.
    """

    def __init__(
        self,
        emb_dim: int = 64,
        process_noise: float = 1e-3,
        observation_noise: float = 1e-2,
        drift_threshold: float = 3.0,
    ) -> None:
        self.emb_dim = emb_dim
        self._q_noise = process_noise
        self._r_noise = observation_noise
        self._drift_threshold = drift_threshold

        # Estimated state (position and velocity), each shape [emb_dim]
        self._x_q: Optional[torch.Tensor] = None
        self._x_p: Optional[torch.Tensor] = None

        # Diagonal covariance — stored as three [emb_dim] variance vectors
        # representing the 2x2 block structure [[P_qq, P_qp], [P_qp, P_pp]]
        self._P_qq: Optional[torch.Tensor] = None
        self._P_qp: Optional[torch.Tensor] = None
        self._P_pp: Optional[torch.Tensor] = None

        self._goal_embedding: Optional[torch.Tensor] = None
        self._initialized: bool = False

        logger.info(
            "EmbeddingKalmanMonitor: emb_dim=%d, process_noise=%.2e, obs_noise=%.2e, threshold=%.1f",
            emb_dim, process_noise, observation_noise, drift_threshold,
        )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def set_goal(self, goal_embedding: torch.Tensor) -> None:
        """
        Initialize the filter at the goal embedding with zero velocity.

        Parameters
        ----------
        goal_embedding : torch.Tensor
            Shape [emb_dim]. The agent's target semantic state.
        """
        g = goal_embedding.float().detach()
        self._goal_embedding = g.clone()
        self._x_q = g.clone()
        self._x_p = torch.zeros_like(g)
        # Start confident about position (low variance), uncertain about velocity
        self._P_qq = torch.full((self.emb_dim,), self._r_noise)
        self._P_qp = torch.zeros(self.emb_dim)
        self._P_pp = torch.ones(self.emb_dim)
        self._initialized = True
        logger.info("EmbeddingKalmanMonitor: goal set, filter initialized.")

    # ------------------------------------------------------------------
    # Core filter steps
    # ------------------------------------------------------------------

    def _predict(self) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Kalman predict step.

        Returns
        -------
        x_q_pred, x_p_pred, P_qq_pred, P_qp_pred, P_pp_pred
        """
        x_q_pred = self._x_q + self._x_p
        x_p_pred = self._x_p.clone()

        # P_pred = F @ P @ F.T + Q, F = [[I, I], [0, I]]
        P_qq_pred = self._P_qq + 2.0 * self._P_qp + self._P_pp + self._q_noise
        P_qp_pred = self._P_qp + self._P_pp
        P_pp_pred = self._P_pp + self._q_noise

        return x_q_pred, x_p_pred, P_qq_pred, P_qp_pred, P_pp_pred

    def update(self, current_emb: torch.Tensor) -> float:
        """
        Run one predict-update cycle with a new embedding observation.

        Call this once per agent step with the latest output embedding.

        Parameters
        ----------
        current_emb : torch.Tensor
            Shape [emb_dim].

        Returns
        -------
        float
            Mean innovation z-score. 0 = on track, high = unexpected jump.
        """
        z = current_emb.float().detach()

        if not self._initialized:
            self._x_q = z.clone()
            self._x_p = torch.zeros_like(z)
            self._P_qq = torch.full((self.emb_dim,), self._r_noise)
            self._P_qp = torch.zeros(self.emb_dim)
            self._P_pp = torch.ones(self.emb_dim)
            self._initialized = True
            return 0.0

        x_q_pred, x_p_pred, P_qq_pred, P_qp_pred, P_pp_pred = self._predict()

        # Innovation and its variance
        innovation = z - x_q_pred
        S = P_qq_pred + self._r_noise

        # Kalman gain
        K_q = P_qq_pred / S
        K_p = P_qp_pred / S

        # State update
        self._x_q = x_q_pred + K_q * innovation
        self._x_p = x_p_pred + K_p * innovation

        # Covariance update: P = (I - K @ H) @ P_pred
        self._P_qq = (1.0 - K_q) * P_qq_pred
        self._P_qp = (1.0 - K_q) * P_qp_pred
        self._P_pp = P_pp_pred - K_p * P_qp_pred

        z_score = float((innovation.abs() / (S.sqrt() + 1e-8)).mean().item())
        logger.debug("Kalman update: mean_z_score=%.4f", z_score)
        return z_score

    # ------------------------------------------------------------------
    # Public monitoring API
    # ------------------------------------------------------------------

    def embedding_velocity(self, current_emb: torch.Tensor) -> torch.Tensor:
        """
        Update the filter and return the estimated velocity p.

        Parameters
        ----------
        current_emb : torch.Tensor
            Shape [emb_dim].

        Returns
        -------
        torch.Tensor
            Kalman-estimated velocity, shape [emb_dim].
        """
        self.update(current_emb)
        return self._x_p.clone() if self._x_p is not None else torch.zeros(self.emb_dim)

    def semantic_drift_score(
        self,
        current_emb: torch.Tensor,
        goal_emb: Optional[torch.Tensor] = None,
    ) -> float:
        """
        Cosine distance between current embedding and goal embedding.

        Range [0, 2]. 0 = identical direction, 2 = opposite.
        Does not advance filter state.
        """
        goal = goal_emb if goal_emb is not None else self._goal_embedding
        if goal is None:
            return 0.0
        cos_sim = F.cosine_similarity(
            current_emb.float().unsqueeze(0),
            goal.float().unsqueeze(0),
        )
        return float(1.0 - cos_sim.item())

    def is_drifting(
        self,
        current_emb: torch.Tensor,
        threshold: Optional[float] = None,
    ) -> bool:
        """
        True if the Kalman innovation z-score exceeds the drift threshold.

        Advances filter state.

        Parameters
        ----------
        current_emb : torch.Tensor
        threshold : float, optional
            Overrides the default drift_threshold set at construction.

        Returns
        -------
        bool
        """
        z_score = self.update(current_emb)
        limit = threshold if threshold is not None else self._drift_threshold
        if z_score > limit:
            logger.warning(
                "Semantic drift detected: z_score=%.4f > threshold=%.4f", z_score, limit
            )
        return z_score > limit

    def energy_drift(self, current_emb: torch.Tensor) -> float:
        """
        Mean innovation z-score after updating the filter.

        Drop-in replacement for the old HNN energy_drift() method.
        0 = no drift, higher = more unexpected semantic change.
        """
        return self.update(current_emb)


# Backward-compatible alias
EmbeddingHamiltonianNN = EmbeddingKalmanMonitor
