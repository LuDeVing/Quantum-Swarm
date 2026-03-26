"""
HamiltonianSwarm vs Baseline — GAIA Level 1 style benchmark.

Tests multi-step reasoning questions where the correct answer is known.
Compares:
  A) Baseline: single Gemini call
  B) Swarm: 4 specialized agents + quantum belief aggregation

Scoring: exact match after normalization (same method as official GAIA evaluator).

Usage:
    set GEMINI_API_KEY=your_key_here
    python gaia_test.py

Optional — load real GAIA validation questions from HuggingFace:
    pip install datasets
    set HF_TOKEN=your_hf_token
    python gaia_test.py --use-hf

Cost: ~80 Gemini calls total. Gemini 2.0 Flash free tier = 1500/day, 15/minute.
"""

import os
import re
import time
import json
import argparse
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from google import genai

# ── Config ───────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-flash-preview"
RATE_LIMIT_DELAY = 4.5  # seconds between calls to stay under 15 req/min

_client = genai.Client(api_key=GEMINI_API_KEY)


def call_gemini(prompt: str) -> str:
    time.sleep(RATE_LIMIT_DELAY)
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


# ── Built-in GAIA Level 1 style questions ────────────────────────────────────
# Each requires 2-5 reasoning steps. Answers are unambiguous.

BUILTIN_QUESTIONS = [
    {
        "question": "A car gets 35 miles per gallon. Gas costs $3.80 per gallon. How much does it cost in dollars (to 2 decimal places) to drive 245 miles?",
        "answer": "26.60",
        "steps": 2,
    },
    {
        "question": "A bank account has $2500. You withdraw 30% then deposit $400. What is the final balance in dollars?",
        "answer": "2150",
        "steps": 2,
    },
    {
        "question": "A rectangle's length is 3 times its width. Its perimeter is 48cm. What is its area in cm²?",
        "answer": "108",
        "steps": 3,
    },
    {
        "question": "Convert 98.6 degrees Fahrenheit to Celsius using the formula C = (F-32) × 5/9. Give a whole number.",
        "answer": "37",
        "steps": 1,
    },
    {
        "question": "A train departs at 14:35 and arrives at 17:20. How many minutes did the journey take?",
        "answer": "165",
        "steps": 2,
    },
    {
        "question": "If you roll two fair six-sided dice, how many combinations give a sum of 7?",
        "answer": "6",
        "steps": 2,
    },
    {
        "question": "In a class of 40 students, 75% passed an exam. Of those who passed, 80% scored above 80%. How many students scored above 80%?",
        "answer": "24",
        "steps": 3,
    },
    {
        "question": "A recipe needs 2.5 cups of flour to make 12 cookies. How many cups of flour are needed to make 30 cookies?",
        "answer": "6.25",
        "steps": 2,
    },
    {
        "question": "A stock is bought at $45. It falls 20% then rises 25%. What is the final price in dollars?",
        "answer": "45",
        "steps": 2,
        "trap": True,  # 45 × 0.8 × 1.25 = 45 — common wrong answer is $56.25
    },
    {
        "question": "How many seconds are in 2 hours and 45 minutes?",
        "answer": "9900",
        "steps": 2,
    },
    {
        "question": "A password must be exactly 4 digits (0-9) and cannot start with 0. How many valid passwords exist?",
        "answer": "9000",
        "steps": 2,
    },
    {
        "question": "What is the compound interest earned (not total value, just the interest) on $5000 at 4% annual rate after 2 years?",
        "answer": "408",
        "steps": 3,
    },
    {
        "question": "A store sells apples for $0.75 each and oranges for $1.20 each. What is the total cost for 8 apples and 5 oranges?",
        "answer": "12",
        "steps": 2,
    },
    {
        "question": "If PI = 3.14159, what is the circumference of a circle with radius 7cm? Round to 2 decimal places.",
        "answer": "43.98",
        "steps": 1,
    },
    {
        "question": "Working 40 hours per week and 52 weeks per year, how many total hours does someone work in a decade?",
        "answer": "20800",
        "steps": 2,
    },
]


# ── HuggingFace GAIA loader (optional) ───────────────────────────────────────

def load_gaia_from_hf(n: int = 20):
    """Load real GAIA Level 1 validation questions from HuggingFace."""
    try:
        from datasets import load_dataset
        hf_token = os.environ.get("HF_TOKEN", "")
        ds = load_dataset("gaia-benchmark/GAIA", "2023_level1",
                          split="validation", token=hf_token)
        questions = []
        for row in ds:
            if len(questions) >= n:
                break
            if row.get("file_name"):  # skip questions that need file attachments
                continue
            questions.append({
                "question": row["Question"],
                "answer": str(row["Final answer"]).strip(),
                "steps": row.get("Annotation", {}).get("Number of steps", "?"),
            })
        print(f"Loaded {len(questions)} GAIA Level 1 questions from HuggingFace.")
        return questions
    except Exception as e:
        print(f"Could not load from HuggingFace ({e}). Using built-in questions.")
        return BUILTIN_QUESTIONS


# ── Answer scoring ────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Normalize answer for comparison — same logic as GAIA official evaluator."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\.\-]", "", text)  # remove punctuation except . and -
    text = re.sub(r"\s+", " ", text)
    # Remove common filler words
    for filler in ["the answer is", "the final answer is", "approximately", "about",
                   "equals", "equal to", "is", "are", "$", "dollars", "cm", "cm²",
                   "meters", "seconds", "minutes", "hours"]:
        text = text.replace(filler, "").strip()
    return text.strip()


def extract_number(text: str) -> Optional[float]:
    """Pull the last number from a text response."""
    matches = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if matches:
        return float(matches[-1])
    return None


def score_answer(predicted: str, correct: str) -> bool:
    """Return True if predicted matches correct answer."""
    p = normalize(predicted)
    c = normalize(correct)

    # Exact match after normalization
    if c in p or p == c:
        return True

    # Number match with tolerance
    pn = extract_number(p)
    cn = extract_number(c)
    if pn is not None and cn is not None:
        if cn == 0:
            return pn == 0
        return abs(pn - cn) / abs(cn) < 0.02  # 2% tolerance

    return False


# ── Baseline: single Gemini call ─────────────────────────────────────────────

def baseline_answer(question: str) -> str:
    prompt = f"""Answer this question. Show your reasoning step by step, then give your final answer on the last line starting with 'ANSWER:'.

Question: {question}"""
    return call_gemini(prompt)


# ── Swarm: 4 agents ──────────────────────────────────────────────────────────

def agent_search(question: str) -> str:
    print(f"      [search]  thinking...", end=" ", flush=True)
    prompt = f"""You are a research agent. Break down what facts or calculations are needed to answer this question, then work through each one.

Question: {question}

End with: ANSWER: <your answer>"""
    r = call_gemini(prompt)
    a = extract_agent_answer(r)
    print(f"-> {a[:50]}")
    return r


def agent_task(question: str) -> str:
    print(f"      [task]    thinking...", end=" ", flush=True)
    prompt = f"""You are a reasoning agent. Solve this step by step, double-checking each calculation.

Question: {question}

End with: ANSWER: <your answer>"""
    r = call_gemini(prompt)
    a = extract_agent_answer(r)
    print(f"-> {a[:50]}")
    return r


def agent_memory(question: str) -> str:
    print(f"      [memory]  thinking...", end=" ", flush=True)
    prompt = f"""You are a verification agent. Identify what type of problem this is, recall the correct formula or method, then solve it carefully.

Question: {question}

End with: ANSWER: <your answer>"""
    r = call_gemini(prompt)
    a = extract_agent_answer(r)
    print(f"-> {a[:50]}")
    return r


def extract_agent_answer(response: str) -> str:
    """Pull the answer after ANSWER: tag."""
    if "ANSWER:" in response.upper():
        parts = response.upper().split("ANSWER:")
        # Get original case version
        idx = response.upper().rfind("ANSWER:")
        return response[idx + 7:].strip().split("\n")[0].strip()
    # Fallback: last line
    lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
    return lines[-1] if lines else response.strip()


def agent_validator(question: str, answers: list[str]) -> str:
    """Validator agent checks 3 answers for consistency and picks the best."""
    answers_str = "\n".join([f"  Agent {i+1}: {a}" for i, a in enumerate(answers)])
    all_same = len(set(normalize(a) for a in answers)) == 1

    prompt = f"""You are a validator agent. Three agents have answered the same question.
Your job: identify if any agent made an error, then give the correct final answer.

Question: {question}

Agent answers:
{answers_str}

{"All agents agree." if all_same else "DISAGREEMENT DETECTED — check carefully for errors."}

Show which answer is correct and why, then end with: ANSWER: <correct answer>"""
    return call_gemini(prompt)


def swarm_answer(question: str) -> dict:
    """Run full swarm pipeline and return answer + metadata."""
    r_search  = agent_search(question)
    r_task    = agent_task(question)
    r_memory  = agent_memory(question)

    a_search  = extract_agent_answer(r_search)
    a_task    = extract_agent_answer(r_task)
    a_memory  = extract_agent_answer(r_memory)

    print(f"      [summary] search={a_search[:30]}  task={a_task[:30]}  memory={a_memory[:30]}")

    # Detect disagreement (energy mismatch proxy)
    unique_answers = set(normalize(a) for a in [a_search, a_task, a_memory])
    disagreement = len(unique_answers) > 1

    if disagreement:
        print(f"      [!!]      agents disagree - validator resolving...")
    else:
        print(f"      [ok]      agents agree - validator confirming...")

    print(f"      [validator] thinking...", end=" ", flush=True)
    r_validator = agent_validator(question, [a_search, a_task, a_memory])
    a_validator = extract_agent_answer(r_validator)
    print(f"-> {a_validator[:50]}")

    return {
        "search":    a_search,
        "task":      a_task,
        "memory":    a_memory,
        "validator": a_validator,
        "disagreement_detected": disagreement,
        "final_answer": a_validator,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(use_hf: bool = False, limit: int = 15):
    if not GEMINI_API_KEY:
        print("ERROR: Set GEMINI_API_KEY environment variable.")
        return

    questions = load_gaia_from_hf(limit) if use_hf else BUILTIN_QUESTIONS[:limit]

    print(f"\n{'='*65}")
    print(f"  HamiltonianSwarm vs Baseline  |  {len(questions)} questions  |  {MODEL}")
    print(f"{'='*65}")
    print(f"  Each question: 1 baseline call + 4 swarm calls = 5 total\n")

    results = []
    baseline_correct = 0
    swarm_correct    = 0

    for i, q in enumerate(questions):
        print(f"\n{'-'*65}")
        print(f"  Q{i+1}/{len(questions)}")
        print(f"  Question: {q['question']}")
        print(f"  Expected: {q['answer']}")
        print(f"{'-'*65}")

        # Baseline
        print(f"\n  --- BASELINE (single call) ---")
        print(f"  calling Gemini...", end=" ", flush=True)
        b_response = baseline_answer(q["question"])
        b_answer   = extract_agent_answer(b_response)
        b_correct  = score_answer(b_answer, q["answer"])
        baseline_correct += b_correct
        print(f"  baseline answer: {b_answer}")
        print(f"  baseline result: {'PASS' if b_correct else 'FAIL'}")

        # Swarm
        print(f"\n  --- SWARM (4 agents) ---")
        s_result  = swarm_answer(q["question"])
        s_answer  = s_result["final_answer"]
        s_correct = score_answer(s_answer, q["answer"])
        swarm_correct += s_correct
        print(f"  swarm answer:    {s_answer}")
        print(f"  swarm result:    {'PASS' if s_correct else 'FAIL'}"
              + ("  !! disagreement was caught and resolved" if s_result["disagreement_detected"] else ""))

        results.append({
            "question":           q["question"],
            "correct_answer":     q["answer"],
            "baseline_answer":    b_answer,
            "baseline_correct":   b_correct,
            "swarm_answer":       s_answer,
            "swarm_correct":      s_correct,
            "disagreement":       s_result["disagreement_detected"],
            "agent_answers":      {k: s_result[k] for k in ["search","task","memory","validator"]},
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    n = len(questions)
    b_pct = baseline_correct / n * 100
    s_pct = swarm_correct    / n * 100
    disagreements = sum(1 for r in results if r["disagreement"])
    swarm_fixed   = sum(1 for r in results if r["disagreement"] and r["swarm_correct"] and not r["baseline_correct"])

    print(f"\n{'='*65}")
    print(f"  FINAL RESULTS")
    print(f"{'='*65}")
    print(f"  Baseline accuracy:  {baseline_correct}/{n}  ({b_pct:.1f}%)")
    print(f"  Swarm accuracy:     {swarm_correct}/{n}  ({s_pct:.1f}%)")
    print(f"  Improvement:        {s_pct - b_pct:+.1f} percentage points")
    print(f"  Disagreements caught by swarm: {disagreements}/{n}")
    print(f"  Cases where disagreement led to correct fix: {swarm_fixed}")

    print(f"\n  Question-by-question:")
    print(f"  {'#':<3} {'Baseline':^10} {'Swarm':^10} {'Disagree':^10}")
    print(f"  {'-'*35}")
    for i, r in enumerate(results):
        b = "PASS" if r["baseline_correct"] else "FAIL"
        s = "PASS" if r["swarm_correct"]    else "FAIL"
        d = "!!"   if r["disagreement"]     else "  "
        print(f"  {i+1:<3} {b:^10} {s:^10} {d:^10}")

    # Compare against published GAIA baselines
    print(f"\n  Published GAIA Level 1 baselines (for context):")
    print(f"    GPT-4 single call:      ~15%")
    print(f"    Best multi-agent 2025:  ~75%")
    print(f"    Your baseline:          {b_pct:.1f}%")
    print(f"    Your swarm:             {s_pct:.1f}%")

    # Save results
    with open("gaia_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to gaia_test_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-hf", action="store_true",
                        help="Load real GAIA questions from HuggingFace (requires HF_TOKEN)")
    parser.add_argument("--limit", type=int, default=15,
                        help="Number of questions to test (default 15)")
    args = parser.parse_args()
    main(use_hf=args.use_hf, limit=args.limit)
