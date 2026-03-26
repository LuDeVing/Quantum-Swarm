"""
Energy H(t) dashboard visualization.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation

logger = logging.getLogger(__name__)


def plot_energy_history(
    energy_histories: Dict[str, List[float]],
    anomaly_indices: Optional[Dict[str, List[int]]] = None,
    title: str = "Agent Energy History",
    save_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Plot H(t) for multiple agents with optional anomaly markers.

    Parameters
    ----------
    energy_histories : dict
        {agent_id: [H_0, H_1, ...]}
    anomaly_indices : dict, optional
        {agent_id: [t1, t2, ...]} — indices where anomalies occurred.
    """
    fig, axes = plt.subplots(2, 1, figsize=(10, 7))
    ax_indiv, ax_total = axes

    colors = plt.cm.tab10(np.linspace(0, 1, max(len(energy_histories), 1)))
    total_energy = None

    for (agent_id, history), color in zip(energy_histories.items(), colors):
        h_arr = np.array(history)
        t = np.arange(len(h_arr))
        ax_indiv.plot(t, h_arr, color=color, label=agent_id, lw=1.5, alpha=0.8)

        if anomaly_indices and agent_id in anomaly_indices:
            for idx in anomaly_indices[agent_id]:
                if idx < len(h_arr):
                    ax_indiv.axvline(idx, color=color, linestyle="--", alpha=0.4)
                    ax_indiv.scatter([idx], [h_arr[idx]], color="red", zorder=5, s=40)

        if total_energy is None:
            total_energy = h_arr.copy()
        else:
            min_len = min(len(total_energy), len(h_arr))
            total_energy = total_energy[:min_len] + h_arr[:min_len]

    ax_indiv.set_ylabel("H(t)"); ax_indiv.set_title(title)
    ax_indiv.legend(fontsize=8); ax_indiv.grid(True, alpha=0.3)

    if total_energy is not None:
        ax_total.plot(total_energy, color="black", lw=2)
        ax_total.set_xlabel("Step"); ax_total.set_ylabel("H_total(t)")
        ax_total.set_title("Total Swarm Energy"); ax_total.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("Energy history plot saved → %s", save_path)
    if show:
        plt.show()
    return fig


def animate_energy_dashboard(
    energy_stream: List[Dict[str, float]],
    interval: int = 100,
    save_path: Optional[str] = None,
) -> animation.FuncAnimation:
    """
    Animate energy dashboard from a stream of {agent_id: H_value} dicts.

    Parameters
    ----------
    energy_stream : list of dict
        Each element is a snapshot: {agent_id: H_value}.
    """
    agent_ids = list(energy_stream[0].keys()) if energy_stream else []
    histories: Dict[str, List[float]] = {aid: [] for aid in agent_ids}

    fig, ax = plt.subplots(figsize=(10, 5))
    lines = {aid: ax.plot([], [], label=aid, lw=1.5)[0] for aid in agent_ids}
    ax.set_xlabel("Step"); ax.set_ylabel("H(t)"); ax.set_title("Live Energy Monitor")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)

    def update(frame):
        snapshot = energy_stream[frame]
        for aid, val in snapshot.items():
            if aid not in histories:
                # Agent joined after the first snapshot — skip silently
                continue
            histories[aid].append(val)
            t = list(range(len(histories[aid])))
            lines[aid].set_data(t, histories[aid])
        ax.relim(); ax.autoscale_view()
        return list(lines.values())

    anim = animation.FuncAnimation(
        fig, update, frames=len(energy_stream), interval=interval, blit=False
    )
    if save_path:
        anim.save(save_path, writer="pillow", fps=10)
        logger.info("Energy animation saved → %s", save_path)
    return anim
