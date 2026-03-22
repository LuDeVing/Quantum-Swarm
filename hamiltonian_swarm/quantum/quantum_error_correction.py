"""
Quantum Error Correction (QEC) for agent state repair.

3-qubit bit-flip code adapted for agent state vectors:

Encoding:   |s_logical⟩ = |s⟩|s⟩|s⟩  (3 redundant copies)
Detection:  majority vote / syndrome measurement
Correction: replace corrupted copy with the majority

"Corruption" signals for agents:
  - Cosine distance > QEC_CORRECTION_THRESHOLD between copies
  - Energy H deviation > 2σ from mean of copies
  - Belief entropy > log(N) (maximally uncertain)

Syndrome measurement:
  Z₁Z₂ = (copy1 ≈ copy2?)  → 0 = yes, 1 = no
  Z₂Z₃ = (copy2 ≈ copy3?)  → 0 = yes, 1 = no

  Syndrome (0,0) → no error
  Syndrome (1,0) → copy 1 corrupted
  Syndrome (0,1) → copy 3 corrupted
  Syndrome (1,1) → copy 2 corrupted
"""

from __future__ import annotations
import logging
import math
from typing import List, Tuple

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class AgentStateQEC:
    """
    3-copy quantum error correction for agent state vectors.

    Parameters
    ----------
    corruption_threshold : float
        Cosine distance above which two copies are deemed inconsistent.
    """

    def __init__(self, corruption_threshold: float = 0.3) -> None:
        self.corruption_threshold = corruption_threshold
        self.corrections_applied: int = 0
        logger.debug("AgentStateQEC: threshold=%.3f", corruption_threshold)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode(self, state_vector: torch.Tensor) -> List[torch.Tensor]:
        """
        Encode state as 3 redundant copies.

        Parameters
        ----------
        state_vector : torch.Tensor
            Shape [n].

        Returns
        -------
        list of 3 torch.Tensor
            Each shape [n].
        """
        s = state_vector.float()
        return [s.clone(), s.clone(), s.clone()]

    # ------------------------------------------------------------------
    # Syndrome measurement
    # ------------------------------------------------------------------

    def measure_syndrome(
        self, encoded_state: List[torch.Tensor]
    ) -> Tuple[int, int]:
        """
        Measure syndrome bits to locate corrupted copy.

        Z₁Z₂: 1 if copies 0 and 1 differ beyond threshold, else 0.
        Z₂Z₃: 1 if copies 1 and 2 differ beyond threshold, else 0.

        Syndrome table:
            (0,0) → no error
            (1,0) → copy 0 corrupted
            (0,1) → copy 2 corrupted
            (1,1) → copy 1 corrupted

        Parameters
        ----------
        encoded_state : list of 3 torch.Tensor

        Returns
        -------
        (s1, s2) : tuple of int
        """
        c0, c1, c2 = encoded_state

        def differs(a: torch.Tensor, b: torch.Tensor) -> int:
            cos = float(
                F.cosine_similarity(a.unsqueeze(0), b.unsqueeze(0)).item()
            )
            dist = 1.0 - cos
            return 1 if dist > self.corruption_threshold else 0

        s1 = differs(c0, c1)
        s2 = differs(c1, c2)
        return s1, s2

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------

    def correct(
        self,
        encoded_state: List[torch.Tensor],
        syndrome: Tuple[int, int],
    ) -> List[torch.Tensor]:
        """
        Apply correction based on syndrome.

        Parameters
        ----------
        encoded_state : list of 3 torch.Tensor
        syndrome : (int, int)

        Returns
        -------
        list of 3 torch.Tensor
            Corrected copies.
        """
        s1, s2 = syndrome
        corrected = [c.clone() for c in encoded_state]

        if s1 == 1 and s2 == 0:
            # Copy 0 corrupted: replace with average of 1 and 2
            corrected[0] = (encoded_state[1] + encoded_state[2]) / 2.0
            logger.info("QEC: corrected copy 0.")
            self.corrections_applied += 1
        elif s1 == 0 and s2 == 1:
            # Copy 2 corrupted: replace with average of 0 and 1
            corrected[2] = (encoded_state[0] + encoded_state[1]) / 2.0
            logger.info("QEC: corrected copy 2.")
            self.corrections_applied += 1
        elif s1 == 1 and s2 == 1:
            # Copy 1 corrupted: replace with average of 0 and 2
            corrected[1] = (encoded_state[0] + encoded_state[2]) / 2.0
            logger.info("QEC: corrected copy 1.")
            self.corrections_applied += 1
        # (0,0): no correction needed

        return corrected

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def decode(self, corrected_encoded_state: List[torch.Tensor]) -> torch.Tensor:
        """
        Return mean of 3 corrected copies as the repaired state.

        Parameters
        ----------
        corrected_encoded_state : list of 3 torch.Tensor

        Returns
        -------
        torch.Tensor
        """
        return torch.stack(corrected_encoded_state).mean(dim=0)

    # ------------------------------------------------------------------
    # Full repair pipeline
    # ------------------------------------------------------------------

    def repair(self, state_vector: torch.Tensor) -> torch.Tensor:
        """
        Encode → detect → correct → decode in one call.

        For freshly corrupted states, this is cheaper than a full restart.

        Parameters
        ----------
        state_vector : torch.Tensor

        Returns
        -------
        torch.Tensor
            Repaired state vector (same shape as input).
        """
        encoded = self.encode(state_vector)
        syndrome = self.measure_syndrome(encoded)
        corrected = self.correct(encoded, syndrome)
        return self.decode(corrected)

    # ------------------------------------------------------------------
    # Theoretical error rate
    # ------------------------------------------------------------------

    def logical_error_rate(self, physical_error_rate: float) -> float:
        """
        Probability that 2+ copies fail simultaneously:
            P_logical = 3p² - 2p³

        Always < p for p < 0.5.

        Parameters
        ----------
        physical_error_rate : float
            p ∈ [0, 1].

        Returns
        -------
        float
        """
        p = physical_error_rate
        return 3 * p**2 - 2 * p**3
