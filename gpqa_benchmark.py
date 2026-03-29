#!/usr/bin/env python3
"""
gpqa_benchmark.py -- Full Algorithm Test on GPQA Diamond Benchmark

Tests the COMPLETE Hamiltonian Swarm algorithm on 20 PhD-level science
questions (the same difficulty as GPQA Diamond used to rank frontier models).

Full algorithm components exercised:
  ActiveInferenceState  -- per-agent health tracking (healthy/uncertain/confused)
                           updated from LLM perplexity each round
  interfere_all()       -- quantum mean-field interference on health belief states
  Anomaly detection     -- z-score on F_health > 2.0 triggers reset + retry
  interfere_weighted()  -- task-anchored weighted interference on answer beliefs (A/B/C/D)
                           agents with more consistent reasoning get higher weight
  RollingContext        -- agents accumulate domain memory across all 20 questions
  Multi-round debate    -- 3 rounds: independent → peer debate → anchored final

Two swarm metrics tracked simultaneously:
  H_swarm_health  -- sum of agent health free energies (agent quality signal)
  H_swarm_answer  -- sum of answer belief entropies (question difficulty signal)

Baseline comparison (GPQA Diamond single-model):
  Random guessing:          25%
  GPT-4o:                  ~53%
  Gemini 2.0 Flash:        ~55%
  Claude 3.5 Sonnet:       ~59%

Output: gpqa_output/gpqa_results.json + gpqa_output/gpqa_test.png
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from dotenv import load_dotenv
from google import genai

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gpqa")

# -- Config -------------------------------------------------------------------
GEMINI_MODEL       = "gemini-2.0-flash"
N_AGENTS           = 9
N_DEBATE_PEERS     = 4
INTERFERENCE_ALPHA = 0.5
MAX_RETRIES        = 1
OUTPUT_DIR         = Path("gpqa_output")
ANSWERS            = ["A", "B", "C", "D"]

# Health belief state
ROLE_PRIOR  = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}
HYPOTHESES  = ["healthy", "uncertain", "confused"]

# -- Load GPQA Diamond dataset (198 questions) --------------------------------

def load_gpqa_questions() -> list:
    """Load all 198 GPQA Diamond questions from HuggingFace, randomise A/B/C/D."""
    from datasets import load_dataset
    token = os.environ.get("HF_TOKEN")
    ds = load_dataset("Idavidrein/gpqa", "gpqa_diamond", token=token)
    rows = ds["train"]

    # Map HF domain names to short labels
    domain_map = {
        "Biology": "biology",
        "Chemistry": "chemistry",
        "Physics": "physics",
    }

    questions = []
    rng = random.Random(42)   # fixed seed → reproducible letter assignment
    for idx, row in enumerate(rows):
        correct_text   = row["Correct Answer"]
        wrong_texts    = [row["Incorrect Answer 1"],
                          row["Incorrect Answer 2"],
                          row["Incorrect Answer 3"]]
        all_answers    = [correct_text] + wrong_texts
        rng.shuffle(all_answers)
        letters        = ["A", "B", "C", "D"]
        correct_letter = letters[all_answers.index(correct_text)]

        domain = domain_map.get(row.get("High-level domain", ""), "other")

        questions.append({
            "id":      idx + 1,
            "domain":  domain,
            "question": row["Question"].strip(),
            "A":       all_answers[0],
            "B":       all_answers[1],
            "C":       all_answers[2],
            "D":       all_answers[3],
            "correct": correct_letter,
        })

    logger.info(f"Loaded {len(questions)} GPQA Diamond questions from HuggingFace.")
    return questions


QUESTIONS = None   # populated at runtime by load_gpqa_questions()

# --------------- (hardcoded questions removed — dataset loaded at runtime) ---

# -- Prompts ------------------------------------------------------------------
PROJECT_BRIEF = (
    "You are a scientist with PhD-level expertise in biology, chemistry, and physics.\n"
    "You are working through a series of difficult graduate-level multiple-choice questions.\n"
    "Think carefully and systematically. Show your reasoning step by step.\n"
    "Conclude every response with EXACTLY: ANSWER: [A|B|C|D]"
)

QUESTION_PROMPT = (
    "{context}"
    "QUESTION {q_id} [{domain}]:\n{question}\n\n"
    "CHOICES:\n  A) {A}\n  B) {B}\n  C) {C}\n  D) {D}\n\n"
    "Reason carefully (4-6 sentences). Conclude with:\nANSWER: [A|B|C|D]"
)

DEBATE_PROMPT = (
    "{context}"
    "QUESTION {q_id} [{domain}]:\n{question}\n\n"
    "CHOICES:\n  A) {A}\n  B) {B}\n  C) {C}\n  D) {D}\n\n"
    "YOUR ROUND 1 REASONING:\n{previous}\n\n"
    "OTHER SCIENTISTS' REASONING:\n{peers}\n\n"
    "Reconsider. Do they raise valid points you missed? Update if needed.\n"
    "Conclude with:\nANSWER: [A|B|C|D]"
)

FINAL_PROMPT = (
    "{context}"
    "QUESTION {q_id} [{domain}]:\n{question}\n\n"
    "CHOICES:\n  A) {A}\n  B) {B}\n  C) {C}\n  D) {D}\n\n"
    "YOUR ROUND 2 REASONING:\n{previous}\n\n"
    "SWARM CONSENSUS: {consensus}\n\n"
    "Give your final answer. Defend your position or update based on consensus.\n"
    "Conclude with:\nANSWER: [A|B|C|D]"
)

# -- Gemini -------------------------------------------------------------------
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options={"api_version": "v1beta"},
        )
    return _client


def llm_call(prompt: str, label: str = "", get_logprobs: bool = False):
    try:
        cfg = {"response_logprobs": True, "logprobs": 3} if get_logprobs else {}
        r = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{PROJECT_BRIEF}\n\n{prompt}",
            **({"config": cfg} if cfg else {}),
        )
        text = r.text.strip()
        tag = f"[{label}] " if label else ""
        logger.info(f"{tag}({len(text)}c): {text[:80]}{'...' if len(text)>80 else ''}")
        if get_logprobs:
            return text, _extract_perplexity(r)
        return text
    except Exception as e:
        logger.error(f"LLM_ERROR [{label}]: {e}")
        return (f"[LLM_ERROR: {e}]\nANSWER: A", 10.0) if get_logprobs else f"[LLM_ERROR]\nANSWER: A"


def _extract_perplexity(response) -> float:
    try:
        lr = response.candidates[0].logprobs_result
        if lr is None:
            return 5.0
        lps = [c.log_probability for c in lr.chosen_candidates
               if c.log_probability is not None and c.log_probability > -1e6]
        return math.exp(-sum(lps) / len(lps)) if lps else 5.0
    except Exception:
        return 5.0


def perplexity_to_similarities(perplexity: float) -> dict:
    """Map LLM perplexity to health-state similarities."""
    confusion = min(math.log(max(perplexity, 1.0)) / math.log(30.0), 1.0)
    return {
        "healthy":   1.0 - 2.0 * confusion,
        "uncertain": 1.0 - 2.0 * abs(confusion - 0.5),
        "confused":  2.0 * confusion - 1.0,
    }


# -- Rolling context ----------------------------------------------------------

class RollingContext:
    """Accumulates agent's question history across the benchmark."""

    def __init__(self, max_recent: int = 3) -> None:
        self.summary    = ""
        self.recent:    list[tuple[int, str]] = []
        self.max_recent = max_recent

    def add_question(self, q_id: int, domain: str, answer: str, output: str) -> None:
        entry = f"Q{q_id} [{domain}]: answered {answer}. Reasoning: {output[:200]}"
        self.recent.append((q_id, entry))
        if len(self.recent) > self.max_recent:
            oldest_id, oldest_text = self.recent.pop(0)
            self._compress(oldest_id, oldest_text)

    def _compress(self, q_id: int, text: str) -> None:
        prompt = (
            "Maintain a concise running summary of a scientist's question analyses.\n\n"
            f"Current summary:\n{self.summary or '(none)'}\n\n"
            f"New entry (Q{q_id}):\n{text}\n\n"
            "Update summary. Max 100 words. Preserve: domains covered, answer patterns. "
            "Reply with ONLY the updated summary."
        )
        result = llm_call(prompt, label="ctx")
        if not result.startswith("[LLM_ERROR"):
            self.summary = result

    def build_context(self) -> str:
        if not self.summary and not self.recent:
            return ""
        parts = []
        if self.summary:
            parts.append(f"YOUR PRIOR ANALYSIS HISTORY:\n{self.summary}")
        for qid, text in self.recent:
            parts.append(f"Q{qid}: {text}")
        sep = "\n" + "-" * 40 + "\n"
        return sep + sep.join(parts) + sep + "\n"


# -- Answer belief utilities --------------------------------------------------

def extract_answer(text: str) -> str:
    m = re.search(r'ANSWER:\s*([ABCD])', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m2 = re.search(r'\b([ABCD])\b[^\w]*$', text.strip(), re.IGNORECASE)
    return m2.group(1).upper() if m2 else "A"


def build_answer_probs(answer: str, output: str) -> np.ndarray:
    """Convert answer + output confidence language to probability vector [A,B,C,D]."""
    t = output.lower()
    if any(w in t for w in ["definitely", "clearly", "must be", "the answer is"]):
        conf = 0.90
    elif any(w in t for w in ["i believe", "likely", "strongly"]):
        conf = 0.75
    elif any(w in t for w in ["possibly", "might", "not sure"]):
        conf = 0.55
    else:
        conf = 0.70
    probs = np.full(4, (1.0 - conf) / 3)
    probs[ANSWERS.index(answer)] = conf
    return probs


def consistency_weight(output: str) -> float:
    """Task-anchor weight: how internally consistent is this reasoning?"""
    t = output.lower()
    length  = min(len(output.split()) / 200.0, 1.0)
    conf    = 1.0 if any(w in t for w in ["therefore", "thus", "clearly", "must be"]) \
              else (0.55 if any(w in t for w in ["maybe", "possibly", "not sure"]) else 0.75)
    struct  = 1.0 if any(w in t for w in ["because", "since", "therefore", "which means"]) else 0.7
    return max(length * conf * struct, 0.1)


def interfere_weighted(beliefs: List[np.ndarray], weights: List[float],
                       alpha: float = 0.5) -> List[np.ndarray]:
    """Task-anchored weighted quantum interference on answer beliefs."""
    w = np.array(weights)
    w = w / w.sum()
    amps     = [np.sqrt(np.clip(b, 1e-10, 1.0)) for b in beliefs]
    combined = sum(wi * a for wi, a in zip(w, amps))
    norm     = float(np.linalg.norm(combined))
    if norm < 1e-10:
        return beliefs
    combined = (combined / norm) ** 2
    combined /= combined.sum()
    return [(1.0 - alpha) * b + alpha * combined for b in beliefs]


def answer_entropy(probs: np.ndarray) -> float:
    p = np.clip(probs, 1e-10, 1.0)
    return float(-np.sum(p * np.log(p)))


def swarm_vote(answers: List[str]) -> str:
    counts = {a: answers.count(a) for a in ANSWERS}
    return max(counts, key=counts.get)


def agreement(answers: List[str]) -> float:
    maj = swarm_vote(answers)
    return sum(1 for a in answers if a == maj) / len(answers)


def consensus_summary(beliefs: List[np.ndarray]) -> str:
    mean_p = np.mean(beliefs, axis=0)
    pairs  = sorted(zip(ANSWERS, mean_p), key=lambda x: -x[1])
    return "Swarm leans " + " | ".join(f"{a}: {p*100:.0f}%" for a, p in pairs if p > 0.05)


# -- Agent class (full algorithm) ---------------------------------------------

class BenchmarkAgent(BaseAgent):
    """
    Full algorithm agent:
      - ActiveInferenceState tracks health (healthy/uncertain/confused) per round
      - RollingContext accumulates question history across the benchmark
      - Answer beliefs tracked separately as a 4-dim probability vector
    """
    def __init__(self, agent_num: int) -> None:
        super().__init__(agent_type=f"bench_{agent_num}", n_dims=3)
        self.agent_num    = agent_num
        self.health_state = ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)
        self.context      = RollingContext()
        self.answer_probs = np.array([0.25, 0.25, 0.25, 0.25])

    async def execute_task(self, task: dict) -> TaskResult:
        return TaskResult(task_id="", agent_id=self.agent_id,
                          success=True, output={}, energy_before=0.0, energy_after=0.0)

    def call(self, prompt: str, label: str) -> tuple:
        """LLM call + perplexity + health state update. Returns (output, answer, F_health)."""
        output, perplexity = llm_call(prompt, label=label, get_logprobs=True)
        sims     = perplexity_to_similarities(perplexity)
        F_health = self.health_state.update(sims)
        answer   = extract_answer(output)
        self.answer_probs = build_answer_probs(answer, output)
        return output, answer, F_health

    def is_anomaly(self) -> bool:
        return self.health_state.is_anomaly()

    def reset_health(self) -> None:
        self.health_state.reset()

    def update_context(self, q_id: int, domain: str, answer: str, output: str) -> None:
        self.context.add_question(q_id, domain, answer, output)

    def get_context(self) -> str:
        return self.context.build_context()


# -- Data records -------------------------------------------------------------

@dataclass
class AgentRecord:
    agent_num:    int
    r1_ans:       str
    r2_ans:       str
    r3_ans:       str
    r1_F_health:  float
    r2_F_health:  float
    r3_F_health:  float
    r1_correct:   bool
    r2_correct:   bool
    r3_correct:   bool
    anomaly_r1:   bool = False
    retried:      bool = False
    r1_weight:    float = 0.0


@dataclass
class QuestionRecord:
    question_id:     int
    domain:          str
    correct:         str
    # Swarm per-round
    r1_ans:          str   = ""
    r2_ans:          str   = ""
    r3_ans:          str   = ""
    r1_correct:      bool  = False
    r2_correct:      bool  = False
    r3_correct:      bool  = False
    r1_agreement:    float = 0.0
    r2_agreement:    float = 0.0
    r3_agreement:    float = 0.0
    # H_swarm (health-space free energy)
    H_health_r1:     float = 0.0
    H_health_r2:     float = 0.0
    H_health_r3:     float = 0.0
    # H_swarm (answer-space entropy)
    H_answer_r1:     float = 0.0
    H_answer_r2:     float = 0.0
    H_answer_r3:     float = 0.0
    n_anomalies:     int   = 0
    n_resets:        int   = 0
    agents:          List[AgentRecord] = field(default_factory=list)


# -- Run one question through full algorithm ----------------------------------

def run_question(q: dict, agents: List[BenchmarkAgent]) -> QuestionRecord:
    correct = q["correct"]
    fmt     = {k: q[k] for k in ["question", "A", "B", "C", "D"]}
    q_id    = q["id"]
    domain  = q["domain"]

    rec = QuestionRecord(question_id=q_id, domain=domain, correct=correct)
    agent_records = []

    # ── Round 1: Independent ─────────────────────────────────────────────
    r1_outputs, r1_answers, r1_weights = {}, {}, {}
    n_anomalies, n_resets = 0, 0

    def r1_call(agent):
        ctx    = agent.get_context()
        prompt = QUESTION_PROMPT.format(context=ctx, q_id=q_id, domain=domain, **fmt)
        output, answer, F_health = agent.call(prompt, label=f"A{agent.agent_num}_R1")
        anomaly = agent.is_anomaly()
        retried = False
        if anomaly:
            logger.warning(f"[A{agent.agent_num}] anomaly R1 (F={F_health:.3f}) -> reset+retry")
            agent.reset_health()
            output, answer, F_health = agent.call(prompt, label=f"A{agent.agent_num}_R1r")
            retried = True
        weight = consistency_weight(output)
        return agent.agent_num, output, answer, F_health, anomaly, retried, weight

    with ThreadPoolExecutor(max_workers=N_AGENTS) as ex:
        futures = [ex.submit(r1_call, a) for a in agents]
        for fut in as_completed(futures):
            num, out, ans, F_h, anom, ret, w = fut.result()
            r1_outputs[num] = out
            r1_answers[num] = ans
            r1_weights[num] = w
            if anom: n_anomalies += 1
            if ret:  n_resets    += 1

    r1_ans_list = [r1_answers[a.agent_num] for a in agents]
    rec.r1_ans       = swarm_vote(r1_ans_list)
    rec.r1_correct   = rec.r1_ans == correct
    rec.r1_agreement = agreement(r1_ans_list)
    rec.H_health_r1  = sum(a.health_state.free_energy() for a in agents)
    rec.H_answer_r1  = sum(answer_entropy(a.answer_probs) for a in agents)
    rec.n_anomalies  = n_anomalies
    rec.n_resets     = n_resets

    # ── Health-space interference after Round 1 ──────────────────────────
    ActiveInferenceState.interfere_all(
        [a.health_state for a in agents], alpha=INTERFERENCE_ALPHA
    )
    # ── Answer-space task-anchored interference after Round 1 ────────────
    weights_list   = [r1_weights[a.agent_num] for a in agents]
    beliefs_list   = [a.answer_probs for a in agents]
    updated_beliefs = interfere_weighted(beliefs_list, weights_list, alpha=INTERFERENCE_ALPHA)
    for i, agent in enumerate(agents):
        agent.answer_probs = updated_beliefs[i]

    # ── Round 2: Debate ───────────────────────────────────────────────────
    r2_outputs, r2_answers = {}, {}

    def r2_call(agent):
        peers = random.sample(
            [a for a in agents if a.agent_num != agent.agent_num],
            min(N_DEBATE_PEERS, N_AGENTS - 1)
        )
        peer_text = "\n---\n".join(
            f"[Scientist {k+1}]:\n{r1_outputs[p.agent_num][:350]}"
            for k, p in enumerate(peers)
        )
        ctx    = agent.get_context()
        prompt = DEBATE_PROMPT.format(
            context=ctx, q_id=q_id, domain=domain, **fmt,
            previous=r1_outputs[agent.agent_num][:450],
            peers=peer_text,
        )
        output, answer, F_health = agent.call(prompt, label=f"A{agent.agent_num}_R2")
        return agent.agent_num, output, answer, F_health

    with ThreadPoolExecutor(max_workers=N_AGENTS) as ex:
        futures = [ex.submit(r2_call, a) for a in agents]
        for fut in as_completed(futures):
            num, out, ans, _ = fut.result()
            r2_outputs[num] = out
            r2_answers[num] = ans

    r2_ans_list = [r2_answers[a.agent_num] for a in agents]
    rec.r2_ans       = swarm_vote(r2_ans_list)
    rec.r2_correct   = rec.r2_ans == correct
    rec.r2_agreement = agreement(r2_ans_list)
    rec.H_health_r2  = sum(a.health_state.free_energy() for a in agents)
    rec.H_answer_r2  = sum(answer_entropy(a.answer_probs) for a in agents)

    # ── Health + answer interference after Round 2 ────────────────────────
    ActiveInferenceState.interfere_all(
        [a.health_state for a in agents], alpha=INTERFERENCE_ALPHA
    )
    r2_weights     = [consistency_weight(r2_outputs[a.agent_num]) for a in agents]
    updated_beliefs = interfere_weighted(
        [a.answer_probs for a in agents], r2_weights, alpha=INTERFERENCE_ALPHA
    )
    for i, agent in enumerate(agents):
        agent.answer_probs = updated_beliefs[i]

    consensus = consensus_summary([a.answer_probs for a in agents])

    # ── Round 3: Final ────────────────────────────────────────────────────
    r3_answers = {}

    def r3_call(agent):
        ctx    = agent.get_context()
        prompt = FINAL_PROMPT.format(
            context=ctx, q_id=q_id, domain=domain, **fmt,
            previous=r2_outputs[agent.agent_num][:450],
            consensus=consensus,
        )
        output, answer, F_health = agent.call(prompt, label=f"A{agent.agent_num}_R3")
        return agent.agent_num, output, answer, F_health

    with ThreadPoolExecutor(max_workers=N_AGENTS) as ex:
        futures = [ex.submit(r3_call, a) for a in agents]
        r3_results = {}
        for fut in as_completed(futures):
            num, out, ans, F_h = fut.result()
            r3_answers[num] = ans
            r3_results[num] = (out, ans, F_h)

    r3_ans_list = [r3_answers[a.agent_num] for a in agents]
    rec.r3_ans       = swarm_vote(r3_ans_list)
    rec.r3_correct   = rec.r3_ans == correct
    rec.r3_agreement = agreement(r3_ans_list)
    rec.H_health_r3  = sum(a.health_state.free_energy() for a in agents)
    rec.H_answer_r3  = sum(answer_entropy(a.answer_probs) for a in agents)

    # ── Update rolling context (parallel) ────────────────────────────────
    def update_ctx(agent):
        out, ans, _ = r3_results[agent.agent_num]
        agent.update_context(q_id, domain, ans, out)

    with ThreadPoolExecutor(max_workers=N_AGENTS) as ex:
        list(ex.map(update_ctx, agents))

    # ── Build per-agent records ───────────────────────────────────────────
    for agent in agents:
        num = agent.agent_num
        agent_records.append(AgentRecord(
            agent_num=num,
            r1_ans=r1_answers[num], r2_ans=r2_answers[num], r3_ans=r3_answers[num],
            r1_F_health=0.0, r2_F_health=0.0, r3_F_health=rec.H_health_r3 / N_AGENTS,
            r1_correct=r1_answers[num] == correct,
            r2_correct=r2_answers[num] == correct,
            r3_correct=r3_answers[num] == correct,
            r1_weight=r1_weights.get(num, 0.0),
        ))
    rec.agents = agent_records

    sym = "✓" if rec.r3_correct else "✗"
    logger.info(
        f"Q{q_id} [{domain}]: R1={rec.r1_ans}{'✓' if rec.r1_correct else '✗'} "
        f"R2={rec.r2_ans}{'✓' if rec.r2_correct else '✗'} "
        f"R3={rec.r3_ans}{sym}  correct={correct}  "
        f"agree_r3={rec.r3_agreement:.2f}  "
        f"H_health={rec.H_health_r3:.3f}  H_ans={rec.H_answer_r3:.3f}  "
        f"resets={n_resets}"
    )
    return rec


# -- Full benchmark -----------------------------------------------------------

def run_benchmark() -> List[QuestionRecord]:
    global QUESTIONS
    if QUESTIONS is None:
        QUESTIONS = load_gpqa_questions()
    agents  = [BenchmarkAgent(i + 1) for i in range(N_AGENTS)]
    records = []
    n_total = len(QUESTIONS)
    for q in QUESTIONS:
        logger.info(f"\n{'='*60}\nQ{q['id']}/{n_total} [{q['domain']}]: {q['question'][:70]}...")
        rec = run_question(q, agents)
        records.append(rec)
        # Running tally
        so_far = [r.r3_correct for r in records]
        logger.info(f"  Running accuracy: {sum(so_far)}/{len(so_far)} = {np.mean(so_far)*100:.1f}%")
    return records


# -- Analysis -----------------------------------------------------------------

def analyze(records: List[QuestionRecord]) -> dict:
    domains = ["biology", "chemistry", "physics"]
    n = len(records)

    def dom_acc(rnd):
        attr = f"r{rnd}_correct"
        return {d: float(np.mean([getattr(r, attr) for r in records if r.domain == d]))
                for d in domains}

    results = {
        "overall": {
            "r1_accuracy": float(np.mean([r.r1_correct for r in records])),
            "r2_accuracy": float(np.mean([r.r2_correct for r in records])),
            "r3_accuracy": float(np.mean([r.r3_correct for r in records])),
            "n_correct_r3": int(sum(r.r3_correct for r in records)),
            "total_anomalies": int(sum(r.n_anomalies for r in records)),
            "total_resets":    int(sum(r.n_resets    for r in records)),
        },
        "by_domain": {
            "r1": dom_acc(1),
            "r3": dom_acc(3),
        },
        "agreement": {
            "r1": float(np.mean([r.r1_agreement for r in records])),
            "r2": float(np.mean([r.r2_agreement for r in records])),
            "r3": float(np.mean([r.r3_agreement for r in records])),
        },
        "H_health": {
            "r1": float(np.mean([r.H_health_r1 for r in records])),
            "r2": float(np.mean([r.H_health_r2 for r in records])),
            "r3": float(np.mean([r.H_health_r3 for r in records])),
        },
        "H_answer": {
            "r1": float(np.mean([r.H_answer_r1 for r in records])),
            "r2": float(np.mean([r.H_answer_r2 for r in records])),
            "r3": float(np.mean([r.H_answer_r3 for r in records])),
        },
        "h_difficulty": {
            "H_correct":   float(np.mean([r.H_answer_r1 for r in records if r.r3_correct])),
            "H_incorrect": float(np.mean([r.H_answer_r1 for r in records if not r.r3_correct])),
        },
    }
    return results


def print_results(results: dict) -> None:
    ov = results["overall"]
    w  = 72
    print("\n" + "=" * w)
    print("  FULL ALGORITHM RESULTS vs SOTA BASELINES")
    print("=" * w)
    baselines = [
        ("Random guessing",           0.25),
        ("GPT-4o (single model)",     0.53),
        ("Gemini 2.0 Flash (single)", 0.55),
        ("Claude 3.5 Sonnet (single)",0.59),
    ]
    for name, acc in baselines:
        print(f"  {name:<35} {acc*100:>6.1f}%  [SOTA baseline]")
    print("-" * w)
    print(f"  {'Swarm R1 (independent vote)':<35} {ov['r1_accuracy']*100:>6.1f}%")
    print(f"  {'Swarm R2 (post-debate)':<35} {ov['r2_accuracy']*100:>6.1f}%")
    print(f"  {'Swarm R3 (full algorithm)':<35} {ov['r3_accuracy']*100:>6.1f}%  "
          f"[{ov['n_correct_r3']}/20 correct]")
    gain = (ov["r3_accuracy"] - ov["r1_accuracy"]) * 100
    print(f"  {'Debate improvement (R1->R3)':<35} {gain:>+6.1f}%")
    print("=" * w)
    print(f"\n  Agreement per round:    R1={results['agreement']['r1']*100:.1f}%  "
          f"R2={results['agreement']['r2']*100:.1f}%  R3={results['agreement']['r3']*100:.1f}%")
    print(f"  H_health (agent health): R1={results['H_health']['r1']:.3f}  "
          f"R2={results['H_health']['r2']:.3f}  R3={results['H_health']['r3']:.3f}")
    print(f"  H_answer (difficulty):   R1={results['H_answer']['r1']:.3f}  "
          f"R2={results['H_answer']['r2']:.3f}  R3={results['H_answer']['r3']:.3f}")
    print(f"  Anomaly resets fired:    {ov['total_resets']} total")
    print(f"\n  Per-domain accuracy (R3):")
    for d in ["biology", "chemistry", "physics"]:
        r1 = results["by_domain"]["r1"][d]
        r3 = results["by_domain"]["r3"][d]
        print(f"    {d:<12}  R1={r1*100:.0f}%  R3={r3*100:.0f}%")
    hd = results["h_difficulty"]
    diff_signal = "YES" if hd["H_incorrect"] > hd["H_correct"] else "NO"
    print(f"\n  H_answer as difficulty signal: {diff_signal}")
    print(f"    Mean H on correct questions:   {hd['H_correct']:.3f}")
    print(f"    Mean H on incorrect questions: {hd['H_incorrect']:.3f}")


# -- Plot ---------------------------------------------------------------------

def plot(results: dict, records: List[QuestionRecord], out_dir: Path) -> Path:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(16, 11))
    gs  = GridSpec(2, 3, figure=fig, hspace=0.44, wspace=0.32)

    C = {"r1": "#f39c12", "r2": "#3498db", "r3": "#2ecc71",
         "sota": "#95a5a6", "h_health": "#e74c3c", "h_ans": "#9b59b6"}
    q_ids = [r.question_id for r in records]

    # (a) Per-question R1 vs R3
    ax1 = fig.add_subplot(gs[0, 0])
    x   = np.arange(len(records))
    ax1.bar(x - 0.2, [int(r.r1_correct) for r in records], 0.38,
            color=C["r1"], alpha=0.8, label="R1 (independent)")
    ax1.bar(x + 0.2, [int(r.r3_correct) for r in records], 0.38,
            color=C["r3"], alpha=0.8, label="R3 (full algo)")
    for sep, lbl, pos in [(6.5, "Biology", 3), (13.5, "Chemistry", 10), (None, "Physics", 17)]:
        if sep: ax1.axvline(sep, color="gray", linestyle=":", linewidth=1)
        ax1.text(pos, 1.08, lbl, ha="center", fontsize=7, color="gray")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"Q{i}" for i in q_ids], rotation=45, fontsize=6)
    ax1.set_title("(a)  Per-Question: R1 vs R3", fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.set_ylim(0, 1.2)

    # (b) Accuracy vs SOTA baselines
    ax2 = fig.add_subplot(gs[0, 1])
    lbls = ["Random\n25%", "GPT-4o\n53%", "Flash\n55%", "Sonnet\n59%",
            "Swarm\nR1", "Swarm\nR2", "Swarm\nR3"]
    vals = [0.25, 0.53, 0.55, 0.59,
            results["overall"]["r1_accuracy"],
            results["overall"]["r2_accuracy"],
            results["overall"]["r3_accuracy"]]
    clrs = [C["sota"]]*4 + [C["r1"], C["r2"], C["r3"]]
    bars = ax2.bar(range(7), [v*100 for v in vals], color=clrs, alpha=0.85, width=0.6)
    ax2.set_xticks(range(7))
    ax2.set_xticklabels(lbls, fontsize=8)
    ax2.set_ylim(0, 105)
    ax2.axvline(3.5, color="black", linestyle="--", linewidth=1, alpha=0.3)
    ax2.set_title("(b)  vs SOTA Baselines", fontweight="bold")
    for bar, val in zip(bars, vals):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 f"{val*100:.0f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")

    # (c) Agreement + accuracy per round
    ax3 = fig.add_subplot(gs[0, 2])
    rounds = [1, 2, 3]
    accs   = [results["overall"][f"r{r}_accuracy"]*100 for r in rounds]
    agrs   = [results["agreement"][f"r{r}"]*100 for r in rounds]
    ax3.plot(rounds, accs, "o-", color=C["r3"], linewidth=2.5, markersize=9, label="Accuracy %")
    ax3b = ax3.twinx()
    ax3b.plot(rounds, agrs, "s--", color="#e67e22", linewidth=2, markersize=7, label="Agreement %")
    ax3.set_xticks([1,2,3])
    ax3.set_xticklabels(["R1\nIndependent", "R2\nDebate", "R3\nFinal"])
    ax3.set_ylabel("Accuracy (%)", color=C["r3"])
    ax3b.set_ylabel("Agreement (%)", color="#e67e22")
    ax3.set_title("(c)  Debate Progression", fontweight="bold")
    for r, a in zip(rounds, accs):
        ax3.text(r, a+1, f"{a:.0f}%", ha="center", fontsize=9, fontweight="bold")
    lines1, lbl1 = ax3.get_legend_handles_labels()
    lines2, lbl2 = ax3b.get_legend_handles_labels()
    ax3.legend(lines1+lines2, lbl1+lbl2, fontsize=7)

    # (d) H_health trajectory (agent quality over rounds)
    ax4 = fig.add_subplot(gs[1, 0])
    ax4.plot(q_ids, [r.H_health_r1 for r in records], "o-",
             color=C["r1"], linewidth=1.5, markersize=5, label="R1")
    ax4.plot(q_ids, [r.H_health_r3 for r in records], "s-",
             color=C["h_health"], linewidth=1.5, markersize=5, label="R3")
    for sep in [7.5, 14.5]:
        ax4.axvline(sep, color="gray", linestyle=":", linewidth=1)
    ax4.set_xlabel("Question ID")
    ax4.set_ylabel("H_swarm_health = sum(F_i)")
    ax4.set_title("(d)  Agent Health Free Energy\n(Active Inference)", fontweight="bold")
    ax4.legend(fontsize=8)

    # (e) H_answer trajectory (question difficulty)
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.bar(q_ids, [r.H_answer_r1 for r in records],
            color=[C["r3"] if r.r3_correct else C["h_health"] for r in records],
            alpha=0.8)
    for sep in [7.5, 14.5]:
        ax5.axvline(sep, color="gray", linestyle=":", linewidth=1)
    ax5.set_xlabel("Question ID")
    ax5.set_ylabel("H_swarm_answer (answer entropy)")
    ax5.set_title("(e)  Answer Entropy per Question\n[green=correct R3, red=wrong R3]",
                  fontweight="bold")
    from matplotlib.patches import Patch
    ax5.legend(handles=[Patch(color=C["r3"], label="Correct R3"),
                        Patch(color=C["h_health"], label="Wrong R3")], fontsize=8)

    # (f) Domain accuracy R1 vs R3
    ax6 = fig.add_subplot(gs[1, 2])
    doms = ["biology", "chemistry", "physics"]
    r1d  = [results["by_domain"]["r1"][d]*100 for d in doms]
    r3d  = [results["by_domain"]["r3"][d]*100 for d in doms]
    xd   = np.arange(3)
    ax6.bar(xd - 0.2, r1d, 0.38, color=C["r1"], alpha=0.8, label="R1")
    ax6.bar(xd + 0.2, r3d, 0.38, color=C["r3"], alpha=0.8, label="R3")
    ax6.set_xticks(xd)
    ax6.set_xticklabels(doms, fontsize=9)
    ax6.set_ylim(0, 105)
    ax6.axhline(55, color="gray", linestyle=":", linewidth=1, label="Gemini baseline")
    ax6.set_ylabel("Accuracy (%)")
    ax6.set_title("(f)  Domain Accuracy R1 vs R3", fontweight="bold")
    ax6.legend(fontsize=8)
    for bars, vals in [(xd - 0.2, r1d), (xd + 0.2, r3d)]:
        for xi, vi in zip(bars, vals):
            ax6.text(xi, vi + 1, f"{vi:.0f}%", ha="center", fontsize=8, fontweight="bold")

    fig.suptitle(
        f"Hamiltonian Swarm — Full Algorithm on GPQA Diamond  |  20 PhD-Level Questions\n"
        f"ActiveInference + interfere_all() + anomaly detection + RollingContext + "
        f"task-anchored interference + 3-round debate  |  {N_AGENTS} agents",
        fontsize=10, fontweight="bold",
    )

    out_path = out_dir / "gpqa_test.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# -- Entry point --------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)
    print(
        f"\nHamiltonian Swarm — Full Algorithm GPQA Benchmark"
        f"\n  Model        : {GEMINI_MODEL}"
        f"\n  Questions    : 20 PhD-level (7 biology, 7 chemistry, 6 physics)"
        f"\n  Agents       : {N_AGENTS} (persistent across all 20 questions)"
        f"\n  Algorithm:"
        f"\n    ActiveInferenceState  -- health tracking per agent per round"
        f"\n    interfere_all()       -- quantum health-space interference"
        f"\n    Anomaly detection     -- z-score > 2.0 triggers reset+retry"
        f"\n    interfere_weighted()  -- task-anchored answer-space interference"
        f"\n    RollingContext        -- domain memory across 20 questions"
        f"\n    3-round debate        -- independent -> debate -> anchored final"
        f"\n  Baselines    : GPT-4o ~53%  Gemini Flash ~55%  Claude 3.5 ~59%"
        f"\n  Est. cost    : ~$1.20"
        f"\n  Est. time    : ~10 minutes\n"
    )

    t0      = time.time()
    records = run_benchmark()
    elapsed = time.time() - t0

    results = analyze(records)
    print_results(results)
    print(f"\n  Total time: {elapsed:.0f}s ({elapsed/60:.1f}m)")

    results_path = OUTPUT_DIR / "gpqa_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"summary": results, "questions": [asdict(r) for r in records]},
                  f, indent=2)

    fig_path = plot(results, records, OUTPUT_DIR)
    print(f"  Figure  -> {fig_path}")
    print(f"  Results -> {results_path}\n")


if __name__ == "__main__":
    main()
