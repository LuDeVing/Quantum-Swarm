"""
Bug Detection Test — HamiltonianSwarm vs Baseline

Tests whether the swarm (one agent per file + cross-file validator)
finds more bugs than a single LLM call given the same codebase.

The buggy_code/ directory has 5 files with 10 known bugs:
  - 6 within-file bugs (easy for single call)
  - 4 cross-file bugs (require seeing 2+ files simultaneously)

Scoring: how many of the 10 known bugs does each approach find?

Usage:
    python bug_detection_test.py

Cost: ~10 Gemini calls total (cheap).
"""

import os
import re
import time
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from google import genai

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-flash-preview"
RATE_LIMIT_DELAY = 4.5  # seconds between calls

_client = genai.Client(api_key=GEMINI_API_KEY)

BUGGY_DIR = Path(__file__).parent / "buggy_code"

# ── Known bugs (ground truth) ─────────────────────────────────────────────────

KNOWN_BUGS = [
    # Within-file bugs
    {
        "id": "BUG1",
        "file": "models.py",
        "type": "within-file",
        "description": "CartItem.subtotal() uses integer division // instead of float multiplication, truncating fractional cents",
        "keywords": ["subtotal", "integer division", "//", "CartItem"],
    },
    {
        "id": "BUG2",
        "file": "models.py",
        "type": "within-file",
        "description": "Cart.total() divides discount_pct by 100, but discount_pct is already a decimal (0.10), so a 10% discount becomes 0.1%",
        "keywords": ["discount", "total", "/ 100", "Cart.total"],
    },
    {
        "id": "BUG3",
        "file": "models.py",
        "type": "within-file",
        "description": "Order.is_shippable() only returns True for 'shipped' status, but 'confirmed' orders should also be shippable",
        "keywords": ["is_shippable", "confirmed", "shipped", "Order"],
    },
    {
        "id": "BUG4",
        "file": "utils.py",
        "type": "within-file",
        "description": "calculate_discount() returns 0.10 for free tier instead of 0.0, giving all users a 10% discount",
        "keywords": ["calculate_discount", "free", "0.10", "return"],
    },
    {
        "id": "BUG5",
        "file": "utils.py",
        "type": "within-file",
        "description": "paginate() treats page as 0-indexed (start = page * page_size) but function is documented as 1-indexed",
        "keywords": ["paginate", "page", "0-indexed", "1-indexed", "off-by-one"],
    },
    {
        "id": "BUG6",
        "file": "database.py",
        "type": "within-file",
        "description": "decrement_stock() uses > instead of >= so it rejects orders where quantity exactly matches available stock",
        "keywords": ["decrement_stock", "stock", "> quantity", ">= quantity"],
    },
    # Cross-file bugs
    {
        "id": "BUG7",
        "file": "database.py + models.py",
        "type": "cross-file",
        "description": "get_cart_by_user() casts user_id to int but models.py stores user_id as string 'u_123' — the cast always fails",
        "keywords": ["get_cart_by_user", "int(user_id", "user_id", "string", "type"],
    },
    {
        "id": "BUG8",
        "file": "api.py + utils.py",
        "type": "cross-file",
        "description": "get_user_profile() reads key 'userId' (camelCase) but utils.build_user_summary() returns 'user_id' (snake_case)",
        "keywords": ["userId", "user_id", "build_user_summary", "camelCase", "snake_case"],
    },
    {
        "id": "BUG9",
        "file": "api.py + models.py",
        "type": "cross-file",
        "description": "apply_promo_code() assigns raw int (e.g. 10.0) to cart.discount_pct, but models.py expects a decimal (0.10) — causes Cart.total() to return negative values",
        "keywords": ["apply_promo_code", "discount_pct", "decimal", "100", "negative"],
    },
    {
        "id": "BUG10",
        "file": "validator.py + models.py",
        "type": "cross-file",
        "description": "validate_user_age() compares user.age (int) against string '18', which raises TypeError at runtime",
        "keywords": ["validate_user_age", "age", "< \"18\"", "string", "int", "TypeError"],
    },
]


# ── File loader ───────────────────────────────────────────────────────────────

def load_file(filename: str) -> str:
    path = BUGGY_DIR / filename
    return path.read_text(encoding="utf-8")


def load_all_files() -> str:
    """Concatenate all files with headers."""
    files = ["models.py", "utils.py", "database.py", "api.py", "validator.py"]
    parts = []
    for f in files:
        content = load_file(f)
        parts.append(f"# ════ FILE: {f} ════\n\n{content}")
    return "\n\n".join(parts)


# ── Gemini call ───────────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str:
    time.sleep(RATE_LIMIT_DELAY)
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_response(response: str, bugs: list) -> tuple[int, list]:
    """
    Count how many known bugs appear to be mentioned in the response.
    Uses keyword matching — a bug is 'found' if at least 2 of its keywords appear.
    Returns (count_found, list_of_found_bug_ids).
    """
    response_lower = response.lower()
    found = []
    for bug in bugs:
        hits = sum(1 for kw in bug["keywords"] if kw.lower() in response_lower)
        if hits >= 2:
            found.append(bug["id"])
    return len(found), found


# ── Baseline: single call with all files ─────────────────────────────────────

def baseline_find_bugs() -> str:
    codebase = load_all_files()
    prompt = f"""You are a senior Python code reviewer. The following codebase is a small e-commerce order system spread across 5 files. It contains multiple bugs — both within individual files and across files (where one file misuses a contract defined in another file).

Your task: find as many bugs as possible. For each bug:
1. Name the file(s) involved
2. Describe the bug precisely
3. Show the incorrect code
4. Explain what the correct code should be

Be thorough. Look especially for:
- Wrong operators or comparisons
- Off-by-one errors
- Type mismatches between files
- Key name mismatches between functions in different files
- Incorrect unit/scale assumptions (e.g. percentage as decimal vs integer)

Here is the full codebase:

{codebase}

LIST ALL BUGS FOUND:"""
    return call_gemini(prompt)


# ── Swarm: one agent per file + cross-file validator ─────────────────────────

def swarm_agent(filename: str) -> str:
    """One agent reviews a single file for within-file bugs."""
    content = load_file(filename)
    prompt = f"""You are a Python code reviewer assigned to review ONE file in isolation.
Find all bugs, suspicious logic, wrong operators, type errors, or off-by-one errors in this file.

For each bug found, state:
- Line(s) involved
- What is wrong
- What the correct code should be

File: {filename}

{content}

BUGS FOUND IN {filename}:"""
    print(f"      [{filename}] reviewing...", end=" ", flush=True)
    result = call_gemini(prompt)
    print(f"({len(result.split())} words)")
    return result


def swarm_cross_file_validator(file_reviews: dict) -> str:
    """
    Cross-file validator sees all per-file reviews AND the actual file contents.
    Its job: find contract mismatches between files.
    """
    # Show the validator the key interfaces from each file
    interface_summary = ""
    for filename, review in file_reviews.items():
        content = load_file(filename)
        interface_summary += f"\n\n# ── {filename} (content + per-file review) ──\n"
        interface_summary += f"## Code:\n{content}\n"
        interface_summary += f"## Per-file review:\n{review}\n"

    prompt = f"""You are a cross-file contract validator. Each file has already been reviewed in isolation.
Your job is ONLY to find bugs that span multiple files — where one file defines a contract (data type, dict key name, unit convention) and another file violates it.

Look specifically for:
1. Dict key name mismatches (e.g. one function returns 'user_id', another reads 'userId')
2. Type mismatches (e.g. one file stores field as string, another casts it to int)
3. Unit/scale mismatches (e.g. one file expects a decimal 0.10, another passes integer 10)
4. Incorrect assumptions about data format defined in a different file

Here are all files with their per-file reviews:

{interface_summary}

CROSS-FILE BUGS FOUND (only bugs that require seeing 2+ files to detect):"""
    print(f"      [cross-file validator] reviewing...", end=" ", flush=True)
    result = call_gemini(prompt)
    print(f"({len(result.split())} words)")
    return result


def swarm_find_bugs() -> str:
    """Run full swarm pipeline: per-file agents + cross-file validator."""
    files = ["models.py", "utils.py", "database.py", "api.py", "validator.py"]

    # Phase 1: per-file agents (sequential due to rate limit)
    reviews = {}
    for f in files:
        reviews[f] = swarm_agent(f)

    # Phase 2: cross-file validator
    cross_file_report = swarm_cross_file_validator(reviews)

    # Combine all findings
    combined = "=== PER-FILE REVIEWS ===\n\n"
    for f, review in reviews.items():
        combined += f"--- {f} ---\n{review}\n\n"
    combined += "=== CROSS-FILE BUGS ===\n\n" + cross_file_report
    return combined


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not GEMINI_API_KEY:
        print("ERROR: Set GEMINI_API_KEY environment variable.")
        return

    within_bugs = [b for b in KNOWN_BUGS if b["type"] == "within-file"]
    cross_bugs  = [b for b in KNOWN_BUGS if b["type"] == "cross-file"]

    print(f"\n{'='*65}")
    print(f"  Bug Detection Test: Swarm vs Baseline")
    print(f"{'='*65}")
    print(f"  Codebase: buggy_code/ (5 files, ~300 lines)")
    print(f"  Known bugs: {len(KNOWN_BUGS)} total")
    print(f"    Within-file: {len(within_bugs)}")
    print(f"    Cross-file:  {len(cross_bugs)}")
    print(f"  Model: {MODEL}")
    print(f"{'='*65}\n")

    # ── Baseline ──────────────────────────────────────────────────────────────
    print("  BASELINE: single Gemini call with full codebase...")
    b_response = baseline_find_bugs()
    b_total, b_found = score_response(b_response, KNOWN_BUGS)
    b_within = [bid for bid in b_found if any(bug["id"] == bid and bug["type"] == "within-file" for bug in KNOWN_BUGS)]
    b_cross  = [bid for bid in b_found if any(bug["id"] == bid and bug["type"] == "cross-file"  for bug in KNOWN_BUGS)]

    print(f"  Baseline found {b_total}/{len(KNOWN_BUGS)} bugs")
    print(f"    Within-file: {len(b_within)}/{len(within_bugs)}  {b_within}")
    print(f"    Cross-file:  {len(b_cross)}/{len(cross_bugs)}   {b_cross}")

    # ── Swarm ─────────────────────────────────────────────────────────────────
    print(f"\n  SWARM: 5 per-file agents + 1 cross-file validator...")
    s_response = swarm_find_bugs()
    s_total, s_found = score_response(s_response, KNOWN_BUGS)
    s_within = [bid for bid in s_found if any(bug["id"] == bid and bug["type"] == "within-file" for bug in KNOWN_BUGS)]
    s_cross  = [bid for bid in s_found if any(bug["id"] == bid and bug["type"] == "cross-file"  for bug in KNOWN_BUGS)]

    print(f"\n  Swarm found {s_total}/{len(KNOWN_BUGS)} bugs")
    print(f"    Within-file: {len(s_within)}/{len(within_bugs)}  {s_within}")
    print(f"    Cross-file:  {len(s_cross)}/{len(cross_bugs)}   {s_cross}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  RESULTS")
    print(f"{'='*65}")
    print(f"  {'Category':<20} {'Baseline':>10} {'Swarm':>10}")
    print(f"  {'-'*42}")
    print(f"  {'Within-file bugs':<20} {len(b_within):>7}/{len(within_bugs)} {len(s_within):>7}/{len(within_bugs)}")
    print(f"  {'Cross-file bugs':<20} {len(b_cross):>7}/{len(cross_bugs)} {len(s_cross):>7}/{len(cross_bugs)}")
    print(f"  {'TOTAL':<20} {b_total:>7}/{len(KNOWN_BUGS)} {s_total:>7}/{len(KNOWN_BUGS)}")

    swarm_advantage = s_total - b_total
    if swarm_advantage > 0:
        print(f"\n  Swarm found {swarm_advantage} more bug(s) than baseline.")
    elif swarm_advantage == 0:
        print(f"\n  Both approaches found the same number of bugs.")
    else:
        print(f"\n  Baseline found {-swarm_advantage} more bug(s) than swarm.")

    print(f"\n  Cross-file bugs missed by baseline but caught by swarm:")
    cross_only = set(s_cross) - set(b_cross)
    if cross_only:
        for bid in cross_only:
            bug = next(b for b in KNOWN_BUGS if b["id"] == bid)
            print(f"    {bid}: {bug['description'][:80]}")
    else:
        print(f"    (none)")

    # Save results
    results = {
        "baseline": {
            "total_found": b_total,
            "within_file": b_within,
            "cross_file": b_cross,
            "response_length": len(b_response),
        },
        "swarm": {
            "total_found": s_total,
            "within_file": s_within,
            "cross_file": s_cross,
            "response_length": len(s_response),
        },
        "known_bugs": KNOWN_BUGS,
    }
    with open("bug_detection_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results saved to bug_detection_results.json")


if __name__ == "__main__":
    main()
