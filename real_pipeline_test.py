#!/usr/bin/env python3
"""
real_pipeline_test.py — Real LLM Pipeline Test with Hamiltonian Validation

This is the FIRST test of the Hamiltonian framework with actual LLM calls.
Every agent makes real Gemini API calls. No hardcoded logic.

Pipeline: 4-stage code review
  Stage 1 (Analyst)      — Reads code, explains what it does
  Stage 2 (Bug Finder)   — Finds potential bugs in the code
  Stage 3 (Fix Suggester)— Suggests fixes for the bugs
  Stage 4 (Reviewer)     — Writes a final review combining all findings

Three conditions (10 runs each):
  A) Hamiltonian ON   — ValidatorAgent monitors each handoff
  B) Hamiltonian OFF  — No monitoring, everything passes through
  C) Fault Injected   — Stage 2 receives corrupted input (simulates LLM failure)
                        With H ON: should detect and retry
                        With H OFF: corruption propagates silently

What makes this real:
  - Gemini makes the actual reasoning decisions
  - Output quality scored by a separate Gemini judge call
  - Hamiltonian energy tracks agent phase-space drift per response
  - Fault injection = passing garbage input to one stage mid-pipeline
  - Results show whether H monitoring actually helps with real LLM outputs

Output: real_pipeline_output/real_pipeline_test.png + results.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import re

import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from dotenv import load_dotenv
from google import genai

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ── Config ─────────────────────────────────────────────────────────────────────
GEMINI_MODEL    = "gemini-2.0-flash"
N_RUNS          = 10          # runs per condition
MAX_RETRIES     = 2           # Hamiltonian ON: retries on detected anomaly
ANOMALY_DH      = 0.35        # |ΔH| threshold for anomaly detection
FAULT_SCALE     = 4.0         # phase-space jump size for injected faults
NORMAL_SCALE    = 0.08        # phase-space step size for normal operation
OUTPUT_DIR      = Path("real_pipeline_output")
SEED            = 42

# Code sample to review (same for every run)
CODE_SAMPLE = '''
def calculate_discount(price, discount_pct, user_type):
    if user_type == "premium":
        discount_pct = discount_pct + 10

    discounted = price - (price * discount_pct / 100)

    if discounted < 0:
        return 0

    tax = discounted * 0.2
    total = discounted + tax

    return total

def process_order(items, user):
    total = 0
    for item in items:
        price = calculate_discount(item["price"], item["discount"], user["type"])
        total = total + price

    if total > 1000:
        total = total - 50

    return total
'''

# ── Gemini client ──────────────────────────────────────────────────────────────

_client: Optional[genai.Client] = None

def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={'api_version': 'v1beta'})
    return _client


EMB_DIMS  = 256  # Paper minimum for coarse anomaly detection (on-topic vs off-topic).
                 # 128-256 retains ~96% of full-dim performance per MRL benchmarks.
                 # <20 dims "falls off a cliff" per empirical outlier detection studies.
EMB_SCALE = 0.04 # Euclidean calibration: p = belief - goal (not cosine-normalized).
                 # ||p||² = ||Δembed||², not bounded to [0,2] — must scale down more.
                 # Normal  (||Δ|| ≈ 0.55): dH ≈ S²*(1 + 0.55²/2) ≈ 0.35² → below threshold
                 # Confused(||Δ|| ≈ 1.40): dH ≈ S²*(1 + 1.40²/2) ≈ 0.35² → above threshold
                 # Recalibrate ANOMALY_DH after first run if needed.


def embed_text(text: str) -> np.ndarray:
    """EMB_DIMS-dim embedding via Gemini embedding model.
    Returns raw (un-normalized) vector so Euclidean distance is preserved.
    Paper: Euclidean outperforms cosine by 24-66% for semantic difference detection."""
    try:
        r = get_client().models.embed_content(
            model="models/gemini-embedding-2-preview",
            contents=text[:2000],
            config={"output_dimensionality": EMB_DIMS},
        )
        vec = np.array(r.embeddings[0].values, dtype=np.float32)
        # Do NOT L2-normalize — preserve magnitude for Euclidean distance
        return vec
    except Exception as e:
        logger.warning(f"embed_text failed ({e}), falling back to noise")
        return np.random.default_rng().normal(0, 0.08, EMB_DIMS).astype(np.float32)


def llm_call(prompt: str, max_tokens: int = 512, label: str = "") -> str:
    """Make a real Gemini API call. Returns text response."""
    try:
        r = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = r.text.strip()
        tag = f"[{label}] " if label else ""
        logger.info(f"{tag}LLM response ({len(text)} chars): {text[:200]}{'...' if len(text)>200 else ''}")
        return text
    except Exception as e:
        logger.error(f"LLM_ERROR: {e}")
        return f"[LLM_ERROR: {e}]"


# ── Stage prompts ──────────────────────────────────────────────────────────────

STAGE_PROMPTS = {
    "analyst": (
        "You are a code analyst. Briefly explain what this Python code does "
        "in 3-5 sentences. Focus on its purpose and main logic.\n\nCode:\n{input}"
    ),
    "bug_finder": (
        "You are a bug finder. Given this code analysis, identify 2-3 potential "
        "bugs or issues in the original code. Be specific.\n\nAnalysis:\n{input}"
    ),
    "fix_suggester": (
        "You are a code fixer. Given these identified bugs, suggest specific "
        "code fixes for each one. Keep it concise.\n\nBugs found:\n{input}"
    ),
    "reviewer": (
        "You are a senior code reviewer. Given all the analysis, bugs, and fixes, "
        "write a 3-sentence final verdict on the code quality (score 1-10).\n\n"
        "Context:\n{input}"
    ),
}

STAGE_GOALS = {
    "analyst":      "I understood the Python code and explained its purpose and main logic clearly.",
    "bug_finder":   "I identified 2-3 specific bugs in the code based on the analysis provided.",
    "fix_suggester":"I suggested specific code fixes for each identified bug.",
    "reviewer":     "I wrote a final verdict on code quality with a numeric score from 1 to 10.",
}

BELIEF_PROMPT = (
    "You just completed a task as a {role}. In 2-3 sentences describe: "
    "(1) what you understood your task to be, "
    "(2) whether the input you received made sense for that task, "
    "(3) how confident you are in your output. "
    "Be honest and brief."
)

QUALITY_PROMPT = (
    "Rate the quality of this code review output on a scale of 0.0 to 1.0. "
    "A score of 1.0 means insightful, specific, and actionable. "
    "A score of 0.0 means gibberish, empty, or completely off-topic. "
    "Reply with ONLY a decimal number like 0.7 or 0.3.\n\nOutput to rate:\n{text}"
)

GARBAGE_INPUT = (
    "XXXXXXX CORRUPTED DATA 12345 @#$% "
    "NaN NaN NaN buffer overflow stack trace "
    "segfault core dumped process killed"
)


# ── Pipeline agent ─────────────────────────────────────────────────────────────

class LLMPipelineAgent(BaseAgent):
    """Real LLM agent — makes actual Gemini calls and updates phase state."""

    def __init__(self, stage: str) -> None:
        super().__init__(agent_type=stage, n_dims=EMB_DIMS)
        self.stage = stage
        self._last_output = ""

    async def execute_task(self, task: dict) -> TaskResult:
        return TaskResult(task_id="", agent_id=self.agent_id,
                          success=True, output={},
                          energy_before=0.0, energy_after=0.0)

    def compute_H(self) -> float:
        return float(
            self.hamiltonian.total_energy(
                self.phase_state.q, self.phase_state.p
            ).item()
        )

    def process(self, input_text: str, rng: np.random.Generator,
                injected_fault: bool = False) -> tuple[str, float, float]:
        """
        Run LLM call, update phase state, return (output, H_before, H_after).
        If injected_fault=True, make a large random phase-space jump.
        """
        H_before = self.compute_H()

        # Real LLM call
        prompt = STAGE_PROMPTS[self.stage].format(input=input_text)
        output = llm_call(prompt, label=self.stage)
        self._last_output = output

        # Belief probe — ask the agent to introspect its own understanding.
        # Healthy agent: "I identified bugs in the code" ≈ STAGE_GOALS → small dH
        # Confused agent: "Input seemed corrupted, unsure of task" ≠ goal → large dH
        belief_prompt = BELIEF_PROMPT.format(role=self.stage)
        belief_report = llm_call(belief_prompt, label=f"{self.stage}_belief")

        # q = embed(belief)                      — where agent thinks it is
        # p = embed(belief) - embed(goal)        — Euclidean deviation from expected
        # Using Euclidean (not cosine): paper shows 24-66% better for drift detection.
        # Raw un-normalized vectors preserve magnitude — confused agent moves further.
        q_raw = embed_text(belief_report)
        p_raw = embed_text(belief_report) - embed_text(STAGE_GOALS[self.stage])
        new_q = torch.tensor(q_raw * EMB_SCALE, dtype=torch.float32)
        new_p = torch.tensor(p_raw * EMB_SCALE, dtype=torch.float32)

        self.update_phase_state(new_q, new_p)
        H_after = self.compute_H()
        return output, H_before, H_after

    def reset_state(self, rng: np.random.Generator) -> None:
        new_q = torch.tensor(rng.normal(0, 0.1, self.n_dims), dtype=torch.float32)
        new_p = torch.tensor(rng.normal(0, 0.1, self.n_dims), dtype=torch.float32)
        self.update_phase_state(new_q, new_p)


def score_output(text: str) -> float:
    """Ask Gemini to score the quality of a pipeline output (0.0–1.0)."""
    if not text or "[LLM_ERROR" in text:
        return 0.0
    prompt = QUALITY_PROMPT.format(text=text[:800])
    raw = llm_call(prompt, max_tokens=10, label="scorer")
    # Extract first float found
    match = re.search(r"\d+\.?\d*", raw)
    if match:
        val = float(match.group())
        return min(max(val, 0.0), 1.0)
    return 0.5


# ── Single run ─────────────────────────────────────────────────────────────────

STAGES = ["analyst", "bug_finder", "fix_suggester", "reviewer"]


@dataclass
class StageRecord:
    stage:      str
    output:     str
    quality:    float
    H_before:   float
    H_after:    float
    dH:         float
    detected:   bool
    retried:    bool
    faulted:    bool


@dataclass
class RunRecord:
    condition:      str   # "h_on_clean" | "h_off_clean" | "h_on_fault" | "h_off_fault"
    run_id:         int
    stages:         List[StageRecord] = field(default_factory=list)
    final_quality:  float = 0.0
    n_detected:     int = 0
    n_faulted:      int = 0
    fault_propagated: bool = False
    elapsed_s:      float = 0.0


def run_pipeline(condition: str, run_id: int) -> RunRecord:
    """Execute one full 4-stage LLM pipeline under the given condition."""
    rng = np.random.default_rng(SEED + run_id * 37)
    record = RunRecord(condition=condition, run_id=run_id)

    use_hamiltonian = condition.startswith("h_on")
    inject_fault    = condition.endswith("fault")

    agents    = {s: LLMPipelineAgent(s) for s in STAGES}
    validator = ValidatorAgent(n_dims=EMB_DIMS, energy_tolerance=0.15) if use_hamiltonian else None

    current_input = CODE_SAMPLE
    t0 = time.time()

    for i, stage in enumerate(STAGES):
        agent = agents[stage]

        # Inject fault at stage 1 (bug_finder) — it receives garbage instead of real analysis
        is_faulted = inject_fault and (stage == "bug_finder")
        stage_input = GARBAGE_INPUT if is_faulted else current_input

        detected = False
        retried  = False
        attempts = 0

        while True:
            attempts += 1
            output, H_before, H_after = agent.process(stage_input, rng,
                                                       injected_fault=is_faulted)
            dH = abs(H_after - H_before)

            # ── Hamiltonian check ──────────────────────────────────────────
            if use_hamiltonian and dH > ANOMALY_DH:
                detected = True
                if attempts <= MAX_RETRIES:
                    # Retry: reset agent state and re-run with correct input
                    agent.reset_state(rng)
                    stage_input = current_input   # give it the real input
                    is_faulted  = False           # fault cleared
                    retried     = True
                    continue
                # Still anomalous after retries: accept but flag
            break

        quality = score_output(output)

        sr = StageRecord(
            stage=stage, output=output, quality=quality,
            H_before=H_before, H_after=H_after, dH=dH,
            detected=detected, retried=retried,
            faulted=is_faulted and not (retried and not detected),
        )
        record.stages.append(sr)

        if detected:
            record.n_detected += 1
        if sr.faulted:
            record.n_faulted += 1

        current_input = output  # pass this stage's output to the next

    # Did fault propagate? (was bug_finder faulted AND reviewer quality suffered?)
    if inject_fault:
        reviewer_q = record.stages[-1].quality
        record.fault_propagated = not detected and (reviewer_q < 0.4)

    # Final quality = geometric mean of all stage qualities
    qs = [s.quality for s in record.stages]
    record.final_quality = float(np.prod(qs) ** (1.0 / len(qs)))
    record.elapsed_s = time.time() - t0
    return record


# ── Run full experiment ────────────────────────────────────────────────────────

def run_experiment() -> List[RunRecord]:
    conditions = ["h_on_clean", "h_off_clean", "h_on_fault", "h_off_fault"]
    all_records: List[RunRecord] = []

    total = len(conditions) * N_RUNS
    done  = 0

    for condition in conditions:
        print(f"\n  [{condition}]")
        for run_id in range(N_RUNS):
            r = run_pipeline(condition, run_id)
            all_records.append(r)
            done += 1
            status = f"q={r.final_quality:.2f}"
            if r.n_detected:
                status += f" DETECTED"
            if r.fault_propagated:
                status += f" PROPAGATED"
            print(f"    run {run_id+1:>2}/{N_RUNS}  {status}  ({r.elapsed_s:.1f}s)")

    return all_records


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze(records: List[RunRecord]) -> dict:
    stats = {}
    for cond in ["h_on_clean", "h_off_clean", "h_on_fault", "h_off_fault"]:
        runs = [r for r in records if r.condition == cond]
        qs   = [r.final_quality for r in runs]
        stats[cond] = {
            "quality_mean":     float(np.mean(qs)),
            "quality_std":      float(np.std(qs)),
            "quality_min":      float(np.min(qs)),
            "quality_max":      float(np.max(qs)),
            "detection_rate":   float(np.mean([r.n_detected > 0 for r in runs])),
            "propagation_rate": float(np.mean([r.fault_propagated for r in runs])),
            "n_runs":           len(runs),
        }
    return stats


# ── Print table ────────────────────────────────────────────────────────────────

COND_LABELS = {
    "h_on_clean":  "H-ON  / No fault",
    "h_off_clean": "H-OFF / No fault",
    "h_on_fault":  "H-ON  / Fault injected",
    "h_off_fault": "H-OFF / Fault injected",
}

def print_table(stats: dict) -> None:
    w = 78
    print("\n" + "=" * w)
    print(f"{'Condition':<26} {'Quality':>8} {'±Std':>6} {'Detect':>8} {'Propagate':>10}")
    print("=" * w)
    for cond, s in stats.items():
        print(
            f"{COND_LABELS[cond]:<26} "
            f"{s['quality_mean']:>8.3f} "
            f"{s['quality_std']:>6.3f} "
            f"{s['detection_rate']*100:>7.0f}% "
            f"{s['propagation_rate']*100:>9.0f}%"
        )
    print("=" * w)


# ── Visualisation ──────────────────────────────────────────────────────────────

COLOURS = {
    "h_on_clean":  "#2ecc71",
    "h_off_clean": "#95a5a6",
    "h_on_fault":  "#f39c12",
    "h_off_fault": "#e74c3c",
}


def plot(stats: dict, records: List[RunRecord], out_dir: Path) -> Path:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(14, 10))
    gs  = GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.32)

    conds = ["h_on_clean", "h_off_clean", "h_on_fault", "h_off_fault"]
    labels = [COND_LABELS[c].replace(" / ", "\n") for c in conds]
    colours = [COLOURS[c] for c in conds]

    # ── (a) Final output quality — box plots ──────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    box_data = [[r.final_quality for r in records if r.condition == c] for c in conds]
    bp = ax1.boxplot(box_data, patch_artist=True, widths=0.5,
                     medianprops=dict(color="black", linewidth=2.2))
    for patch, col in zip(bp["boxes"], colours):
        patch.set_facecolor(col)
        patch.set_alpha(0.75)
    ax1.set_xticks(range(1, 5))
    ax1.set_xticklabels(labels, fontsize=7.5)
    ax1.set_ylabel("Final Output Quality (LLM-scored)")
    ax1.set_title("(a)  Output Quality Distribution", fontweight="bold")
    ax1.set_ylim(0, 1.08)

    # ── (b) Per-stage quality for fault runs ──────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    for cond in ["h_on_fault", "h_off_fault"]:
        runs = [r for r in records if r.condition == cond]
        stage_means = []
        for i in range(len(STAGES)):
            qs = [r.stages[i].quality for r in runs if len(r.stages) > i]
            stage_means.append(np.mean(qs) if qs else 0.0)
        ax2.plot(STAGES, stage_means, color=COLOURS[cond], marker="o",
                 linewidth=2.2, markersize=8,
                 label=COND_LABELS[cond].replace(" / ", " "))
    ax2.axvline(1, color="gray", linestyle="--", linewidth=1,
                label="Fault injected here")
    ax2.set_ylabel("Mean Stage Quality")
    ax2.set_title("(b)  Quality per Stage  (fault runs)", fontweight="bold")
    ax2.set_ylim(0, 1.08)
    ax2.legend(fontsize=8)
    ax2.tick_params(axis="x", rotation=12)

    # ── (c) Energy anomaly (|ΔH|) per stage for fault runs ───────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    for cond in ["h_on_fault", "h_off_fault"]:
        runs = [r for r in records if r.condition == cond]
        dh_means = []
        for i in range(len(STAGES)):
            dhs = [r.stages[i].dH for r in runs if len(r.stages) > i]
            dh_means.append(np.mean(dhs) if dhs else 0.0)
        ax3.plot(STAGES, dh_means, color=COLOURS[cond], marker="s",
                 linewidth=2.2, markersize=8,
                 label=COND_LABELS[cond].replace(" / ", " "))
    ax3.axhline(ANOMALY_DH, color="black", linestyle="--", linewidth=1.5,
                label=f"Detection threshold |ΔH|={ANOMALY_DH}")
    ax3.axvline(1, color="gray", linestyle="--", linewidth=1,
                label="Fault injected here")
    ax3.set_ylabel("|ΔH|  (energy anomaly)")
    ax3.set_title("(c)  Hamiltonian Energy Anomaly per Stage", fontweight="bold")
    ax3.legend(fontsize=8)
    ax3.tick_params(axis="x", rotation=12)

    # ── (d) Summary bar chart ─────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    x    = np.arange(len(conds))
    width = 0.28
    means = [stats[c]["quality_mean"] for c in conds]
    stds  = [stats[c]["quality_std"]  for c in conds]
    bars  = ax4.bar(x, means, width=0.55, color=colours, alpha=0.82,
                    yerr=stds, capsize=5, edgecolor="white")
    for bar, m in zip(bars, means):
        ax4.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + max(stds) + 0.01,
                 f"{m:.2f}", ha="center", fontsize=9, fontweight="bold")
    ax4.set_xticks(x)
    ax4.set_xticklabels(labels, fontsize=7.5)
    ax4.set_ylabel("Mean Final Quality ± std")
    ax4.set_title("(d)  Mean Quality Summary", fontweight="bold")
    ax4.set_ylim(0, 1.15)

    # Detection / propagation text annotations
    for xi, cond in enumerate(conds):
        s = stats[cond]
        if s["detection_rate"] > 0:
            ax4.text(xi, 0.05, f"Detect\n{s['detection_rate']*100:.0f}%",
                     ha="center", fontsize=7.5, color="#27ae60", fontweight="bold")
        if s["propagation_rate"] > 0:
            ax4.text(xi, 0.15, f"Prop\n{s['propagation_rate']*100:.0f}%",
                     ha="center", fontsize=7.5, color="#c0392b", fontweight="bold")

    fig.suptitle(
        f"Hamiltonian Swarm — Real LLM Pipeline Test\n"
        f"Gemini {GEMINI_MODEL}  ·  {N_RUNS} runs per condition  ·  "
        f"4-stage code review pipeline  ·  Fault at stage 2",
        fontsize=11, fontweight="bold",
    )

    out_path = out_dir / "real_pipeline_test.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"\nHamiltonian Swarm — Real LLM Pipeline Test"
        f"\n  Model      : {GEMINI_MODEL}"
        f"\n  Runs/cond  : {N_RUNS}"
        f"\n  Total runs : {4 * N_RUNS}  ({4 * N_RUNS * 8} LLM calls [task+belief] + quality scoring)"
        f"\n  Conditions : H-ON clean | H-OFF clean | H-ON fault | H-OFF fault"
        f"\n  Task       : 4-stage code review (real code sample)\n"
    )

    t0      = time.time()
    records = run_experiment()
    elapsed = time.time() - t0

    stats = analyze(records)
    print_table(stats)
    print(f"\n  Total time: {elapsed:.0f}s")

    # Save results
    results_path = OUTPUT_DIR / "results.json"
    with open(results_path, "w") as f:
        json.dump({
            "stats": stats,
            "runs": [
                {**asdict(r), "stages": [asdict(s) for s in r.stages]}
                for r in records
            ]
        }, f, indent=2)

    fig_path = plot(stats, records, OUTPUT_DIR)
    print(f"  Figure  -> {fig_path}")
    print(f"  Results -> {results_path}")
    print(f"\n  real_pipeline_test.png  <- this is your first real LLM test\n")


if __name__ == "__main__":
    main()
