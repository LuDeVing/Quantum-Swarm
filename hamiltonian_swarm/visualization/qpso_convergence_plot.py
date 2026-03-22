"""
QPSO particle convergence visualizer.
"""

from __future__ import annotations
import logging
from typing import List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation

logger = logging.getLogger(__name__)


def plot_qpso_convergence(
    convergence_history: List[float],
    diversity_history: Optional[List[float]] = None,
    title: str = "QPSO Convergence",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Plot gbest value vs iteration, with optional diversity overlay.

    Parameters
    ----------
    convergence_history : list of float
        gbest value at each iteration.
    diversity_history : list of float, optional
        Mean particle spread at each iteration.
    """
    fig, axes = plt.subplots(1 + (diversity_history is not None), 1, figsize=(9, 6))
    if not isinstance(axes, np.ndarray):
        axes = [axes]

    iters = np.arange(len(convergence_history))
    axes[0].plot(iters, convergence_history, "b-", lw=2)
    axes[0].set_ylabel("gbest value"); axes[0].set_title(title)
    axes[0].grid(True, alpha=0.3); axes[0].set_yscale("symlog")

    if diversity_history is not None:
        axes[1].plot(np.arange(len(diversity_history)), diversity_history, "g-", lw=1.5)
        axes[1].set_xlabel("Iteration"); axes[1].set_ylabel("Diversity (σ)")
        axes[1].grid(True, alpha=0.3)
    else:
        axes[0].set_xlabel("Iteration")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("QPSO convergence plot saved → %s", save_path)
    if show:
        plt.show()
    return fig


def animate_qpso(
    position_snapshots: List[np.ndarray],
    gbest_history: List[np.ndarray],
    dim_x: int = 0,
    dim_y: int = 1,
    interval: int = 80,
    save_path: Optional[str] = None,
) -> animation.FuncAnimation:
    """
    Animate QPSO particle positions converging in 2D projection.

    Parameters
    ----------
    position_snapshots : list of np.ndarray
        Each shape [n_particles, n_dims] — particle positions per iteration.
    gbest_history : list of np.ndarray
        Global best position per iteration.
    dim_x, dim_y : int
        Which dimensions to project onto.
    """
    all_pos = np.concatenate(position_snapshots)
    x_min, x_max = all_pos[:, dim_x].min(), all_pos[:, dim_x].max()
    y_min, y_max = all_pos[:, dim_y].min(), all_pos[:, dim_y].max()

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.set_xlim(x_min - 0.5, x_max + 0.5)
    ax.set_ylim(y_min - 0.5, y_max + 0.5)
    ax.set_xlabel(f"dim {dim_x}"); ax.set_ylabel(f"dim {dim_y}")
    ax.set_title("QPSO Particle Convergence")

    scat = ax.scatter([], [], s=20, c="steelblue", alpha=0.7)
    gbest_pt, = ax.plot([], [], "r*", ms=14, label="gbest")
    ax.legend()

    iter_text = ax.text(0.02, 0.95, "", transform=ax.transAxes, fontsize=10)

    def update(frame):
        pos = position_snapshots[frame]
        scat.set_offsets(pos[:, [dim_x, dim_y]])
        gb = gbest_history[frame]
        gbest_pt.set_data([gb[dim_x]], [gb[dim_y]])
        iter_text.set_text(f"iter {frame}")
        return scat, gbest_pt, iter_text

    anim = animation.FuncAnimation(
        fig, update, frames=len(position_snapshots), interval=interval, blit=True
    )
    if save_path:
        anim.save(save_path, writer="pillow", fps=15)
        logger.info("QPSO animation saved → %s", save_path)
    return anim
