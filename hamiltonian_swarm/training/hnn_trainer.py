"""
Training loop for the Hamiltonian Neural Network (HNN).

Supports:
  - Adam optimizer with cosine annealing LR schedule
  - Gradient clipping
  - Validation energy conservation error
  - Best-checkpoint saving
"""

from __future__ import annotations
import logging
import os
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from ..core.hamiltonian_nn import HamiltonianNN
from .dataset_generator import PhaseSpaceDataset, generate_harmonic_oscillator
from .loss_functions import hamiltonian_loss

logger = logging.getLogger(__name__)


class HNNTrainer:
    """
    Trainer for HamiltonianNN.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality.
    hidden_dim : int
        HNN hidden layer width.
    n_layers : int
        Number of hidden layers.
    learning_rate : float
    epochs : int
    batch_size : int
    grad_clip : float
    lambda_conservation : float
    mu_symplectic : float
    checkpoint_path : str
        Directory to save checkpoints.
    """

    def __init__(
        self,
        n_dims: int = 1,
        hidden_dim: int = 256,
        n_layers: int = 3,
        learning_rate: float = 1e-3,
        epochs: int = 100,
        batch_size: int = 256,
        grad_clip: float = 1.0,
        lambda_conservation: float = 0.5,
        mu_symplectic: float = 0.1,
        checkpoint_path: str = "checkpoints",
    ) -> None:
        self.n_dims = n_dims
        self.epochs = epochs
        self.batch_size = batch_size
        self.grad_clip = grad_clip
        self.lambda_conservation = lambda_conservation
        self.mu_symplectic = mu_symplectic
        self.checkpoint_path = checkpoint_path

        self.model = HamiltonianNN(n_dims=n_dims, hidden_dim=hidden_dim, n_layers=n_layers)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=epochs, eta_min=learning_rate * 0.01
        )

        self.train_losses: List[float] = []
        self.val_losses: List[float] = []
        self.best_val_loss: float = float("inf")

        os.makedirs(checkpoint_path, exist_ok=True)
        logger.info(
            "HNNTrainer: n_dims=%d, epochs=%d, batch=%d", n_dims, epochs, batch_size
        )

    # ------------------------------------------------------------------
    # Training loop
    # ------------------------------------------------------------------

    def train(
        self,
        dataset: Optional[PhaseSpaceDataset] = None,
        val_fraction: float = 0.2,
    ) -> Dict[str, List[float]]:
        """
        Run the full training loop.

        Parameters
        ----------
        dataset : PhaseSpaceDataset, optional
            If None, generates a SHO dataset automatically.
        val_fraction : float
            Fraction of data held out for validation.

        Returns
        -------
        dict with 'train_losses' and 'val_losses'.
        """
        if dataset is None:
            logger.info("No dataset provided — generating SHO data.")
            q, p, dqdt, dpdt = generate_harmonic_oscillator(n_trajectories=100)
            dataset = PhaseSpaceDataset(q, p, dqdt, dpdt)

        n_val = int(len(dataset) * val_fraction)
        n_train = len(dataset) - n_val
        train_ds, val_ds = random_split(dataset, [n_train, n_val])

        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=self.batch_size, shuffle=False)

        for epoch in range(self.epochs):
            self.model.train()
            epoch_loss = 0.0
            for q_b, p_b, dqdt_b, dpdt_b in train_loader:
                self.optimizer.zero_grad()
                loss, _ = hamiltonian_loss(
                    self.model, q_b, p_b, dqdt_b, dpdt_b,
                    lambda_conservation=self.lambda_conservation,
                    mu_symplectic=self.mu_symplectic,
                )
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip)
                self.optimizer.step()
                epoch_loss += loss.item()

            epoch_loss /= len(train_loader)
            self.train_losses.append(epoch_loss)
            self.scheduler.step()

            # Validation
            val_loss = self._validate(val_loader)
            self.val_losses.append(val_loss)

            if val_loss < self.best_val_loss:
                self.best_val_loss = val_loss
                self._save_checkpoint(epoch)

            if epoch % 10 == 0:
                logger.info(
                    "Epoch %d/%d: train_loss=%.6f, val_loss=%.6f, lr=%.2e",
                    epoch,
                    self.epochs,
                    epoch_loss,
                    val_loss,
                    self.scheduler.get_last_lr()[0],
                )

        return {"train_losses": self.train_losses, "val_losses": self.val_losses}

    def _validate(self, val_loader: DataLoader) -> float:
        """Compute validation energy conservation error."""
        self.model.eval()
        total_error = 0.0
        with torch.no_grad():
            for q_b, p_b, _, _ in val_loader:
                error = self.model.energy_error(q_b, p_b)
                total_error += float(error.item())
        return total_error / len(val_loader)

    def _save_checkpoint(self, epoch: int) -> None:
        """Save model state dict to checkpoint directory."""
        path = os.path.join(self.checkpoint_path, f"hnn_best.pt")
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "val_loss": self.best_val_loss,
            },
            path,
        )
        logger.info("Checkpoint saved at epoch %d → %s", epoch, path)

    def load_checkpoint(self, path: str) -> None:
        """Load model weights from a checkpoint file."""
        ckpt = torch.load(path, map_location="cpu")
        self.model.load_state_dict(ckpt["model_state_dict"])
        self.optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        self.best_val_loss = ckpt.get("val_loss", float("inf"))
        logger.info("Checkpoint loaded from %s (epoch=%d)", path, ckpt.get("epoch", -1))
