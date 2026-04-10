"""Stance probabilities, consistency scoring, and belief-space interference."""

from __future__ import annotations

import math
import re
from typing import List

import numpy as np

__all__ = [
    "perplexity_to_similarities",
    "interfere_weighted",
    "extract_stance_probs",
    "consistency_weight",
]


def perplexity_to_similarities(perplexity: float) -> dict:
    confusion = min(math.log(max(perplexity, 1.0)) / math.log(30.0), 1.0)
    return {
        "healthy":   max(0.0, min(1.0, 1.0 - 2.0 * confusion)),
        "uncertain": max(0.0, min(1.0, 1.0 - 2.0 * abs(confusion - 0.5))),
        "confused":  max(0.0, min(1.0, 2.0 * confusion - 1.0)),
    }


def interfere_weighted(
    beliefs: List[np.ndarray],
    weights: List[float],
    alpha: float = 0.5,
) -> List[np.ndarray]:
    w = np.array(weights, dtype=float)
    w = w / w.sum()
    amps     = [np.sqrt(np.clip(b, 1e-10, 1.0)) for b in beliefs]
    combined = sum(wi * a for wi, a in zip(w, amps))
    norm     = float(np.linalg.norm(combined))
    if norm < 1e-10:
        return beliefs
    combined = (combined / norm) ** 2
    combined /= combined.sum()
    return [(1.0 - alpha) * b + alpha * combined for b in beliefs]


def extract_stance_probs(output: str) -> np.ndarray:
    tag_match = re.search(r"\bSTANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)\b", output, re.IGNORECASE)
    if tag_match:
        tag = tag_match.group(1).upper()
        idx = {"MINIMAL": 0, "ROBUST": 1, "SCALABLE": 2, "PRAGMATIC": 3}.get(tag, 3)
        scores = np.full(4, 0.5)
        scores[idx] = 4.0
        return scores / scores.sum()
    text = output.lower()
    scores = np.array([
        sum(1 for w in ["simple", "minimal", "straightforward", "basic",
                         "lean", "lightweight", "easy", "small"] if w in text),
        sum(1 for w in ["robust", "reliable", "error handling", "fallback",
                         "resilient", "defensive", "retry", "fault"] if w in text),
        sum(1 for w in ["scalable", "extensible", "modular", "distributed",
                         "horizontal", "growth", "microservice", "queue"] if w in text),
        sum(1 for w in ["pragmatic", "practical", "tradeoff", "balance",
                         "reasonable", "sufficient", "good enough", "ship"] if w in text),
    ], dtype=float)
    scores += 0.5
    return scores / scores.sum()


def consistency_weight(output: str) -> float:
    length_score = min(len(output) / 2000, 1.0)
    logic_words  = sum(1 for w in ["because", "therefore", "however", "thus", "since",
                                    "which means", "as a result", "consequently"] if w in output.lower())
    tech_words   = sum(1 for w in ["function", "class", "endpoint", "schema", "service",
                                    "interface", "module", "database", "api", "test",
                                    "component", "route", "model", "controller"] if w in output.lower())
    return 0.4 * length_score + 0.3 * min(logic_words / 5, 1.0) + 0.3 * min(tech_words / 10, 1.0)
