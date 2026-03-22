"""
Phase-space (q, p) trajectory visualizer.

Provides:
  - plot_phase_portrait : static (q vs p) portrait with energy coloring
  - animate_phase_portrait : animated trajectory
"""

from __future__ import annotations
import logging
from typing import List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation

from ..core.phase_space import PhaseSpaceState

logger = logging.getLogger(__name__)


def plot_phase_portrait(
    trajectory: List[PhaseSpaceState],
    dim: int = 0,
    title: str = "Phase Portrait",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Plot q[dim] vs p[dim] phase portrait, colored by time.

    Parameters
    ----------
    trajectory : list of PhaseSpaceState
    dim : int
        Which dimension to plot (for multi-dim systems).
    title : str
    save_path : str, optional
    show : bool

    Returns
    -------
    matplotlib Figure
    """
    qs = np.array([float(s.q[dim].item()) for s in trajectory])
    ps = np.array([float(s.p[dim].item()) for s in trajectory])
    times = np.linspace(0, 1, len(trajectory))

    fig, ax = plt.subplots(figsize=(7, 6))
    sc = ax.scatter(qs, ps, c=times, cmap="viridis", s=5, alpha=0.8)
    plt.colorbar(sc, ax=ax, label="Normalized time")
    ax.set_xlabel(f"q[{dim}]")
    ax.set_ylabel(f"p[{dim}]")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("Phase portrait saved → %s", save_path)
    if show:
        plt.show()
    return fig


def animate_phase_portrait(
    trajectory: List[PhaseSpaceState],
    dim: int = 0,
    interval: int = 50,
    save_path: Optional[str] = None,
) -> animation.FuncAnimation:
    """
    Animate (q, p) trajectory.

    Parameters
    ----------
    trajectory : list of PhaseSpaceState
    dim : int
    interval : int
        Milliseconds between frames.
    save_path : str, optional
        Save as GIF if provided.

    Returns
    -------
    FuncAnimation
    """
    qs = np.array([float(s.q[dim].item()) for s in trajectory])
    ps = np.array([float(s.p[dim].item()) for s in trajectory])

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.set_xlim(qs.min() - 0.1, qs.max() + 0.1)
    ax.set_ylim(ps.min() - 0.1, ps.max() + 0.1)
    ax.set_xlabel(f"q[{dim}]"); ax.set_ylabel(f"p[{dim}]")
    ax.set_title("Phase Portrait Animation")

    line, = ax.plot([], [], "b-", lw=1, alpha=0.6)
    point, = ax.plot([], [], "ro", ms=6)

    def init():
        line.set_data([], []); point.set_data([], [])
        return line, point

    def update(frame):
        line.set_data(qs[:frame], ps[:frame])
        point.set_data([qs[frame]], [ps[frame]])
        return line, point

    anim = animation.FuncAnimation(
        fig, update, frames=len(trajectory), init_func=init, interval=interval, blit=True
    )
    if save_path:
        anim.save(save_path, writer="pillow", fps=20)
        logger.info("Phase portrait animation saved → %s", save_path)
    return anim
