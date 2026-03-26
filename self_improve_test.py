"""
Self-Improvement Test — HamiltonianSwarm reviews its own code.

The swarm's own codebase is ~10,700 lines across 6 modules.
That's too large for a single prompt.

Approaches compared:
  A) Baseline: single Gemini call with the 5 most important files (~1,700 lines)
  B) Swarm: one agent per module (6 agents) + cross-module validator

Each produces a list of improvement suggestions.
We score by: total suggestions, unique cross-module insights, and quality tags.

Usage:
    python self_improve_test.py

Cost: ~8 Gemini calls.
"""

import os
import time
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from google import genai

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-flash-preview"
RATE_LIMIT_DELAY = 4.5

_client = genai.Client(api_key=GEMINI_API_KEY)
ROOT = Path(__file__).parent / "hamiltonian_swarm"

# ── Module groupings ──────────────────────────────────────────────────────────
# Each swarm agent owns one module (a set of related files).

MODULES = {
    "core": [
        "core/hamiltonian.py",
        "core/conservation_monitor.py",
        "core/phase_space.py",
        "core/information_entropy.py",
    ],
    "quantum": [
        "quantum/qpso.py",
        "quantum/quantum_state.py",
        "quantum/schrodinger.py",
        "quantum/quantum_annealing.py",
    ],
    "agents": [
        "agents/base_agent.py",
        "agents/orchestrator.py",
        "agents/validator_agent.py",
        "agents/memory_agent.py",
    ],
    "evolution": [
        "evolution/evolutionary_loop.py",
        "evolution/fitness_evaluator.py",
        "evolution/mutation_engine.py",
        "evolution/genome.py",
    ],
    "coordination": [
        "coordination/shared_belief_state.py",
        "coordination/entanglement_registry.py",
        "coordination/quantum_coalition.py",
    ],
    "market": [
        "market/polymarket_agent.py",
        "examples/polymarket_prediction.py",
    ],
}

# Baseline gets the 5 most central files (what fits in ~1,700 lines)
BASELINE_FILES = [
    "core/hamiltonian.py",
    "quantum/qpso.py",
    "agents/orchestrator.py",
    "agents/base_agent.py",
    "coordination/shared_belief_state.py",
]


# ── File loader ───────────────────────────────────────────────────────────────

def load_file(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        return f"# [FILE NOT FOUND: {relative_path}]\n"
    return path.read_text(encoding="utf-8", errors="replace")


def load_module(files: list) -> str:
    parts = []
    for f in files:
        content = load_file(f)
        parts.append(f"# ════ {f} ════\n\n{content}")
    return "\n\n".join(parts)


# ── Gemini call ───────────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str:
    time.sleep(RATE_LIMIT_DELAY)
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


# ── Scoring ───────────────────────────────────────────────────────────────────

IMPROVEMENT_CATEGORIES = [
    ("performance",    ["slow", "bottleneck", "cache", "O(n", "redundant", "recompute", "vectori"]),
    ("correctness",    ["bug", "wrong", "incorrect", "off-by-one", "overflow", "underflow", "race condition", "deadlock"]),
    ("numerical",      ["numerical", "float", "precision", "nan", "inf", "division by zero", "overflow", "stability"]),
    ("architecture",   ["coupling", "interface", "contract", "circular", "dependency", "abstraction", "separation"]),
    ("cross-module",   ["between", "across", "inconsistent", "mismatch", "module", "integration", "protocol"]),
    ("scalability",    ["scale", "large", "memory", "parallel", "concurrent", "distributed", "async"]),
]


def score_response(text: str) -> dict:
    text_lower = text.lower()
    # Count bullet points / numbered items as suggestions
    import re
    bullets = len(re.findall(r"^\s*[-*\d]+[\.\)]\s", text, re.MULTILINE))
    categories = {}
    for cat, keywords in IMPROVEMENT_CATEGORIES:
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits > 0:
            categories[cat] = hits
    return {
        "suggestion_count": bullets,
        "word_count": len(text.split()),
        "categories": categories,
        "category_count": len(categories),
    }


# ── Baseline: single call, 5 core files ───────────────────────────────────────

def baseline_review() -> str:
    print("  Loading baseline files...")
    code = ""
    for f in BASELINE_FILES:
        content = load_file(f)
        lines = len(content.splitlines())
        print(f"    {f}: {lines} lines")
        code += f"# ════ {f} ════\n\n{content}\n\n"

    total_lines = len(code.splitlines())
    print(f"  Total: {total_lines} lines sent to single call")

    prompt = f"""You are a senior AI systems engineer reviewing a quantum-inspired multi-agent framework called HamiltonianSwarm.

The system coordinates LLM agents using Hamiltonian mechanics and Quantum Particle Swarm Optimization (QPSO).
Your task: identify concrete improvements across these files.

For each improvement:
1. State which file and line(s) are affected
2. Describe the problem clearly
3. Suggest a specific fix or alternative approach
4. Tag it: [performance] [correctness] [numerical] [architecture] [scalability]

Focus on:
- Numerical stability in QPSO and Hamiltonian conservation
- Agent coordination bottlenecks
- Architectural coupling between modules
- Missing error handling at critical points
- Scalability limits

Here is the code:

{code}

IMPROVEMENT SUGGESTIONS:"""

    print("  Calling Gemini (single call)...", end=" ", flush=True)
    result = call_gemini(prompt)
    print(f"({len(result.split())} words)")
    return result


# ── Swarm: per-module agents ───────────────────────────────────────────────────

def module_agent(module_name: str, files: list) -> str:
    code = load_module(files)
    lines = len(code.splitlines())
    print(f"      [{module_name}] {lines} lines, calling Gemini...", end=" ", flush=True)

    prompt = f"""You are a specialist code reviewer for the '{module_name}' module of HamiltonianSwarm, a quantum-inspired multi-agent AI framework.

Review ONLY this module. Find concrete improvements:
- Bugs, numerical instability, wrong logic
- Performance bottlenecks
- Poor abstractions or missing error handling
- Interface assumptions that might break when called from other modules

For each issue, state:
1. File and approximate line
2. Problem description
3. Suggested fix
4. Tag: [performance] [correctness] [numerical] [architecture] [scalability]

Module: {module_name}
Files: {', '.join(files)}

Code:
{code}

ISSUES IN {module_name.upper()} MODULE:"""

    result = call_gemini(prompt)
    print(f"({len(result.split())} words)")
    return result


def cross_module_validator(module_reviews: dict) -> str:
    print("      [cross-module validator] calling Gemini...", end=" ", flush=True)

    # Build a compact interface summary (not full code — too large)
    summary = ""
    for module_name, review in module_reviews.items():
        files = MODULES[module_name]
        summary += f"\n\n## Module: {module_name} ({', '.join(files)})\n"
        summary += f"### Per-module review findings:\n{review[:2000]}\n"  # cap per-module

    prompt = f"""You are a cross-module integration reviewer for HamiltonianSwarm.

Each module has already been reviewed in isolation. Your job is to find issues that ONLY appear when looking across modules:

1. Interface mismatches — where module A assumes a format/type that module B doesn't provide
2. Inconsistent abstractions — where two modules solve the same problem differently
3. Missing coordination — where module A's output should feed into module B but doesn't
4. Redundant implementations — duplicated logic across modules
5. Coupling violations — where a module reaches into another module's internals

Here are the per-module reviews:
{summary}

The key modules are:
- core: Hamiltonian mechanics, conservation laws, phase space
- quantum: QPSO optimizer, quantum state, Schrödinger evolution
- agents: base agent, orchestrator, validator, memory
- evolution: evolutionary loop, fitness, mutation, genome
- coordination: shared belief state, entanglement, coalitions
- market: Polymarket integration, prediction agents

CROSS-MODULE ISSUES (only issues requiring 2+ modules to detect):"""

    result = call_gemini(prompt)
    print(f"({len(result.split())} words)")
    return result


def swarm_review() -> tuple[dict, str]:
    module_reviews = {}
    for module_name, files in MODULES.items():
        module_reviews[module_name] = module_agent(module_name, files)

    cross = cross_module_validator(module_reviews)
    return module_reviews, cross


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not GEMINI_API_KEY:
        print("ERROR: Set GEMINI_API_KEY environment variable.")
        return

    total_lines = sum(
        len(load_file(f).splitlines())
        for files in MODULES.values()
        for f in files
    )

    print(f"\n{'='*65}")
    print(f"  Self-Improvement Test: Swarm reviews its own code")
    print(f"{'='*65}")
    print(f"  Codebase: hamiltonian_swarm/  ({total_lines} lines, {sum(len(v) for v in MODULES.values())} files)")
    print(f"  Baseline sees: {len(BASELINE_FILES)} files (~1,700 lines)")
    print(f"  Swarm sees: all {len(MODULES)} modules via {len(MODULES)} agents + validator")
    print(f"{'='*65}\n")

    # Baseline
    print("  ── BASELINE (single call, 5 core files) ──")
    b_response = baseline_review()
    b_score = score_response(b_response)

    # Swarm
    print(f"\n  ── SWARM ({len(MODULES)} module agents + cross-module validator) ──")
    s_module_reviews, s_cross = swarm_review()
    s_combined = "\n\n".join(s_module_reviews.values()) + "\n\n" + s_cross
    s_score = score_response(s_combined)
    s_cross_score = score_response(s_cross)

    # Results
    print(f"\n{'='*65}")
    print(f"  RESULTS")
    print(f"{'='*65}")
    print(f"  {'Metric':<30} {'Baseline':>12} {'Swarm':>12}")
    print(f"  {'-'*56}")
    print(f"  {'Suggestions (bullet points)':<30} {b_score['suggestion_count']:>12} {s_score['suggestion_count']:>12}")
    print(f"  {'Words generated':<30} {b_score['word_count']:>12} {s_score['word_count']:>12}")
    print(f"  {'Improvement categories hit':<30} {b_score['category_count']:>12} {s_score['category_count']:>12}")
    print(f"  {'Files reviewed':<30} {len(BASELINE_FILES):>12} {sum(len(v) for v in MODULES.values()):>12}")
    print(f"  {'Lines of code seen':<30} {'~1,700':>12} {total_lines:>12}")

    print(f"\n  Categories baseline found: {list(b_score['categories'].keys())}")
    print(f"  Categories swarm found:    {list(s_score['categories'].keys())}")

    print(f"\n  Cross-module validator categories: {list(s_cross_score['categories'].keys())}")
    print(f"  Cross-module suggestions: {s_cross_score['suggestion_count']}")

    # Save
    results = {
        "baseline": {"score": b_score, "response": b_response},
        "swarm": {
            "score": s_score,
            "cross_module_score": s_cross_score,
            "module_reviews": s_module_reviews,
            "cross_module_review": s_cross,
        },
    }
    with open("self_improve_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n  Full suggestions saved to self_improve_results.json")
    print(f"\n  Key insight: baseline sees {len(BASELINE_FILES)}/{sum(len(v) for v in MODULES.values())} files.")
    print(f"  Swarm covers the full codebase — cross-module issues are only visible to the swarm.")


if __name__ == "__main__":
    main()
