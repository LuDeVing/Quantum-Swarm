"""
HNN for stock price prediction.

Encodes stock dynamics in Hamiltonian form:
    q = normalized price series (position)
    p = rate of change / momentum (conjugate momentum)
    H(q,p) = market energy (conserved if market is in equilibrium)

Demonstrates: HNNTrainer on a synthetic price trajectory.
"""

from __future__ import annotations
import logging
import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("stock_hnn")

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.training.hnn_trainer import HNNTrainer
from hamiltonian_swarm.training.dataset_generator import PhaseSpaceDataset


def generate_stock_data(
    n_series: int = 200,
    n_steps: int = 100,
    dt: float = 1.0,
    noise: float = 0.02,
) -> PhaseSpaceDataset:
    """
    Simulate stock prices as damped harmonic oscillators with noise.

    q = normalized price, p = price momentum (daily return)
    """
    all_q, all_p, all_dqdt, all_dpdt = [], [], [], []

    for _ in range(n_series):
        # Random initial price & momentum
        q0 = np.random.uniform(0.5, 2.0)
        p0 = np.random.uniform(-0.1, 0.1)
        q, p = q0, p0
        for _ in range(n_steps):
            dqdt = p + np.random.randn() * noise
            dpdt = -0.1 * q + np.random.randn() * noise  # mean-reverting
            all_q.append([[q]])
            all_p.append([[p]])
            all_dqdt.append([[dqdt]])
            all_dpdt.append([[dpdt]])
            q += dt * dqdt
            p += dt * dpdt

    q_t = torch.tensor(all_q, dtype=torch.float32).squeeze()
    p_t = torch.tensor(all_p, dtype=torch.float32).squeeze()
    dqdt_t = torch.tensor(all_dqdt, dtype=torch.float32).squeeze()
    dpdt_t = torch.tensor(all_dpdt, dtype=torch.float32).squeeze()

    return PhaseSpaceDataset(
        q_t.unsqueeze(-1), p_t.unsqueeze(-1),
        dqdt_t.unsqueeze(-1), dpdt_t.unsqueeze(-1),
    )


if __name__ == "__main__":
    logger.info("Generating synthetic stock dataset...")
    dataset = generate_stock_data(n_series=300, n_steps=80)
    logger.info("Dataset size: %d samples", len(dataset))

    trainer = HNNTrainer(
        n_dims=1,
        hidden_dim=128,
        n_layers=3,
        learning_rate=1e-3,
        epochs=50,
        batch_size=128,
        lambda_conservation=0.5,
        checkpoint_path="checkpoints/stock",
    )

    logger.info("Training HNN on stock dynamics...")
    history = trainer.train(dataset=dataset, val_fraction=0.2)

    logger.info("Training complete!")
    logger.info("Final train loss: %.6f", history["train_losses"][-1])
    logger.info("Final val loss:   %.6f", history["val_losses"][-1])
    logger.info("Best val loss:    %.6f", trainer.best_val_loss)
