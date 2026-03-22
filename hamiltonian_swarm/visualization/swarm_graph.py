"""
Agent graph topology visualizer using NetworkX.

Node size     ∝ current task queue size
Edge width    ∝ communication frequency
Node color    = energy stability (green=stable, red=drifting)
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False
    logger.warning("networkx not installed — swarm_graph.py will be non-functional.")


def plot_swarm_graph(
    agent_states: List[Dict[str, Any]],
    communication_counts: Optional[Dict[str, Dict[str, int]]] = None,
    stability_scores: Optional[Dict[str, float]] = None,
    title: str = "Swarm Agent Graph",
    save_path: Optional[str] = None,
    show: bool = False,
) -> Optional[plt.Figure]:
    """
    Draw the agent communication graph.

    Parameters
    ----------
    agent_states : list of dict
        Each dict from agent.serialize_state(). Must contain 'agent_id'.
    communication_counts : dict, optional
        {sender_id: {receiver_id: count}}
    stability_scores : dict, optional
        {agent_id: drift_score}. 0 = stable (green), 1 = drifting (red).
    """
    if not _HAS_NX:
        logger.error("networkx required for swarm graph visualization.")
        return None

    G = nx.DiGraph()

    # Add nodes
    for state in agent_states:
        aid = state["agent_id"]
        queue_size = state.get("queue_size", 1)
        G.add_node(aid, queue_size=queue_size, agent_type=state.get("agent_type", "?"))

    # Add edges
    if communication_counts:
        for sender, receivers in communication_counts.items():
            for receiver, count in receivers.items():
                if sender in G and receiver in G:
                    G.add_edge(sender, receiver, weight=count)

    # Node sizes proportional to load
    node_sizes = [max(300, G.nodes[n].get("queue_size", 1) * 200) for n in G.nodes()]

    # Node colors: green=stable, red=drifting
    node_colors = []
    for n in G.nodes():
        if stability_scores:
            score = stability_scores.get(n, 0.0)
            r = min(1.0, score * 10)
            g = max(0.0, 1.0 - score * 10)
            node_colors.append((r, g, 0.2))
        else:
            node_colors.append("steelblue")

    # Edge widths proportional to communication frequency
    edge_widths = [
        max(0.5, G[u][v].get("weight", 1) / 10.0) for u, v in G.edges()
    ]

    fig, ax = plt.subplots(figsize=(10, 8))
    pos = nx.spring_layout(G, seed=42)
    nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=8, ax=ax)
    if G.edges():
        nx.draw_networkx_edges(G, pos, width=edge_widths, edge_color="gray",
                               arrows=True, ax=ax, connectionstyle="arc3,rad=0.1")

    ax.set_title(title); ax.axis("off")

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("Swarm graph saved → %s", save_path)
    if show:
        plt.show()
    return fig
