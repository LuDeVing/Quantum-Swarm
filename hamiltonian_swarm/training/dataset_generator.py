"""
Synthetic phase-space trajectory dataset generator.

Systems implemented:
  1. Simple Harmonic Oscillator : H = p²/2 + q²/2  (analytic)
  2. Nonlinear Pendulum          : H = p²/2 - cos(q) (numerical)
  3. Double Well                 : H = p²/2 + (q²-1)²
  4. Hénon–Heiles (2D chaos)    : H = ½(p₁²+p₂²) + ½(q₁²+q₂²) + q₁²q₂ - q₂³/3
"""

from __future__ import annotations
import logging
from typing import List, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Integrators (scipy-free, simple RK4)
# ──────────────────────────────────────────────────────────────────────

def _rk4_step(q: np.ndarray, p: np.ndarray, dt: float, dHdq, dHdp) -> Tuple[np.ndarray, np.ndarray]:
    """Single RK4 step for Hamilton's equations."""
    def f(q_, p_):
        return dHdp(q_, p_), -dHdq(q_, p_)

    k1q, k1p = f(q, p)
    k2q, k2p = f(q + dt/2*k1q, p + dt/2*k1p)
    k3q, k3p = f(q + dt/2*k2q, p + dt/2*k2p)
    k4q, k4p = f(q + dt*k3q, p + dt*k3p)

    q_new = q + dt/6 * (k1q + 2*k2q + 2*k3q + k4q)
    p_new = p + dt/6 * (k1p + 2*k2p + 2*k3p + k4p)
    return q_new, p_new


def _integrate(q0, p0, dHdq, dHdp, dt=0.05, n_steps=100):
    """Integrate a Hamiltonian system via RK4, returning trajectory arrays."""
    qs, ps = [q0.copy()], [p0.copy()]
    q, p = q0.copy(), p0.copy()
    for _ in range(n_steps):
        q, p = _rk4_step(q, p, dt, dHdq, dHdp)
        qs.append(q.copy())
        ps.append(p.copy())
    return np.array(qs), np.array(ps)


# ──────────────────────────────────────────────────────────────────────
# System definitions
# ──────────────────────────────────────────────────────────────────────

def generate_harmonic_oscillator(
    n_trajectories: int = 200,
    n_steps: int = 100,
    dt: float = 0.05,
    noise_std: float = 0.01,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Simple Harmonic Oscillator: H = p²/2 + q²/2.

    Analytic solution:
        q(t) = A cos(t + φ)
        p(t) = -A sin(t + φ)

    Returns (q_traj, p_traj, dqdt, dpdt), each shape [N*T, 1].
    """
    dHdq = lambda q, p: q
    dHdp = lambda q, p: p

    all_q, all_p, all_dqdt, all_dpdt = [], [], [], []
    for _ in range(n_trajectories):
        q0 = np.random.uniform(-2.0, 2.0, size=(1,))
        p0 = np.random.uniform(-2.0, 2.0, size=(1,))
        qs, ps = _integrate(q0, p0, dHdq, dHdp, dt=dt, n_steps=n_steps)
        dqdts = np.array([dHdp(q, p) for q, p in zip(qs, ps)])
        dpdts = np.array([-dHdq(q, p) for q, p in zip(qs, ps)])

        all_q.append(qs); all_p.append(ps)
        all_dqdt.append(dqdts); all_dpdt.append(dpdts)

    q = np.concatenate(all_q) + np.random.randn(*np.concatenate(all_q).shape) * noise_std
    p = np.concatenate(all_p) + np.random.randn(*np.concatenate(all_p).shape) * noise_std
    dqdt = np.concatenate(all_dqdt)
    dpdt = np.concatenate(all_dpdt)

    logger.info("SHO dataset: %d samples", len(q))
    return (
        torch.tensor(q, dtype=torch.float32),
        torch.tensor(p, dtype=torch.float32),
        torch.tensor(dqdt, dtype=torch.float32),
        torch.tensor(dpdt, dtype=torch.float32),
    )


def generate_pendulum(
    n_trajectories: int = 200,
    n_steps: int = 100,
    dt: float = 0.05,
    noise_std: float = 0.01,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Nonlinear Pendulum: H = p²/2 - cos(q).

    dHdq = sin(q), dHdp = p.
    """
    dHdq = lambda q, p: np.sin(q)
    dHdp = lambda q, p: p

    all_q, all_p, all_dqdt, all_dpdt = [], [], [], []
    for _ in range(n_trajectories):
        q0 = np.random.uniform(-np.pi + 0.1, np.pi - 0.1, size=(1,))
        p0 = np.random.uniform(-1.5, 1.5, size=(1,))
        qs, ps = _integrate(q0, p0, dHdq, dHdp, dt=dt, n_steps=n_steps)
        dqdts = np.array([dHdp(q, p) for q, p in zip(qs, ps)])
        dpdts = np.array([-dHdq(q, p) for q, p in zip(qs, ps)])
        all_q.append(qs); all_p.append(ps)
        all_dqdt.append(dqdts); all_dpdt.append(dpdts)

    q = np.concatenate(all_q) + np.random.randn(*np.concatenate(all_q).shape) * noise_std
    p = np.concatenate(all_p) + np.random.randn(*np.concatenate(all_p).shape) * noise_std
    logger.info("Pendulum dataset: %d samples", len(q))
    return (
        torch.tensor(q, dtype=torch.float32),
        torch.tensor(p, dtype=torch.float32),
        torch.tensor(np.concatenate(all_dqdt), dtype=torch.float32),
        torch.tensor(np.concatenate(all_dpdt), dtype=torch.float32),
    )


def generate_double_well(
    n_trajectories: int = 200,
    n_steps: int = 100,
    dt: float = 0.05,
    noise_std: float = 0.01,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Double Well: H = p²/2 + (q²-1)².

    dHdq = 4q(q²-1), dHdp = p.
    """
    dHdq = lambda q, p: 4 * q * (q**2 - 1)
    dHdp = lambda q, p: p

    all_q, all_p, all_dqdt, all_dpdt = [], [], [], []
    for _ in range(n_trajectories):
        q0 = np.random.uniform(-1.5, 1.5, size=(1,))
        p0 = np.random.uniform(-1.5, 1.5, size=(1,))
        qs, ps = _integrate(q0, p0, dHdq, dHdp, dt=dt, n_steps=n_steps)
        dqdts = np.array([dHdp(q, p) for q, p in zip(qs, ps)])
        dpdts = np.array([-dHdq(q, p) for q, p in zip(qs, ps)])
        all_q.append(qs); all_p.append(ps)
        all_dqdt.append(dqdts); all_dpdt.append(dpdts)

    q = np.concatenate(all_q) + np.random.randn(*np.concatenate(all_q).shape) * noise_std
    p = np.concatenate(all_p) + np.random.randn(*np.concatenate(all_p).shape) * noise_std
    logger.info("Double-well dataset: %d samples", len(q))
    return (
        torch.tensor(q, dtype=torch.float32),
        torch.tensor(p, dtype=torch.float32),
        torch.tensor(np.concatenate(all_dqdt), dtype=torch.float32),
        torch.tensor(np.concatenate(all_dpdt), dtype=torch.float32),
    )


def generate_henon_heiles(
    n_trajectories: int = 200,
    n_steps: int = 100,
    dt: float = 0.05,
    noise_std: float = 0.01,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Hénon–Heiles (2D chaos):
        H = ½(p₁²+p₂²) + ½(q₁²+q₂²) + q₁²q₂ - q₂³/3

    dH/dq₁ = q₁ + 2q₁q₂
    dH/dq₂ = q₂ + q₁² - q₂²
    dH/dp  = p
    """
    def dHdq(q, p):
        return np.array([q[0] + 2*q[0]*q[1], q[1] + q[0]**2 - q[1]**2])
    def dHdp(q, p):
        return p

    all_q, all_p, all_dqdt, all_dpdt = [], [], [], []
    for _ in range(n_trajectories):
        q0 = np.random.uniform(-0.4, 0.4, size=(2,))
        p0 = np.random.uniform(-0.4, 0.4, size=(2,))
        qs, ps = _integrate(q0, p0, dHdq, dHdp, dt=dt, n_steps=n_steps)
        dqdts = np.array([dHdp(q, p) for q, p in zip(qs, ps)])
        dpdts = np.array([-dHdq(q, p) for q, p in zip(qs, ps)])
        all_q.append(qs); all_p.append(ps)
        all_dqdt.append(dqdts); all_dpdt.append(dpdts)

    q = np.concatenate(all_q) + np.random.randn(*np.concatenate(all_q).shape) * noise_std
    p = np.concatenate(all_p) + np.random.randn(*np.concatenate(all_p).shape) * noise_std
    logger.info("Hénon–Heiles dataset: %d samples", len(q))
    return (
        torch.tensor(q, dtype=torch.float32),
        torch.tensor(p, dtype=torch.float32),
        torch.tensor(np.concatenate(all_dqdt), dtype=torch.float32),
        torch.tensor(np.concatenate(all_dpdt), dtype=torch.float32),
    )


class PhaseSpaceDataset(Dataset):
    """
    PyTorch Dataset wrapping (q, p, dq/dt, dp/dt) trajectory data.

    Parameters
    ----------
    q, p, dqdt, dpdt : torch.Tensor
        Phase-space data arrays.
    """

    def __init__(
        self,
        q: torch.Tensor,
        p: torch.Tensor,
        dqdt: torch.Tensor,
        dpdt: torch.Tensor,
    ) -> None:
        assert q.shape == p.shape == dqdt.shape == dpdt.shape, "Shape mismatch."
        self.q = q
        self.p = p
        self.dqdt = dqdt
        self.dpdt = dpdt

    def __len__(self) -> int:
        return len(self.q)

    def __getitem__(self, idx: int):
        return self.q[idx], self.p[idx], self.dqdt[idx], self.dpdt[idx]
