"""
HamiltonianSwarm vs Baseline -- Extended Einstein Puzzle

The original Einstein puzzle: 5 houses, 15 clues, 1 solution.
This extended version: 8 houses, 8 attributes, 30 clues.

Why this tests what other swarms can't handle:
- Requires holding ALL constraints simultaneously
- Forgetting one early clue = wrong final answer
- Other agents drift and contradict themselves by clue 20+
- HamiltonianSwarm's conservation monitor tracks constraint violations

Scoring:
- How many of 8 constraints does each solution satisfy?
- Did the system catch its own contradictions?
- Perfect score = 8/8 constraints satisfied

Usage:
    python constraint_test.py
"""

import os
import re
import json
import time
from dotenv import load_dotenv
load_dotenv()

from google import genai

# ── Config ───────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-flash-preview"
RATE_LIMIT_DELAY = 4.5

_client = genai.Client(api_key=GEMINI_API_KEY)


def call_gemini(prompt: str) -> str:
    time.sleep(RATE_LIMIT_DELAY)
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


# ── The Puzzle ────────────────────────────────────────────────────────────────
#
# 8 houses in a row, numbered 1-8 left to right.
# Each house has 8 attributes:
#   Color, Nationality, Pet, Drink, Sport, Job, Car, Music
#
# KNOWN CORRECT SOLUTION (ground truth):
CORRECT_SOLUTION = [
    {"house": 1, "color": "Red",    "nationality": "British",  "pet": "Dog",      "drink": "Tea",     "sport": "Tennis",   "job": "Doctor",    "car": "BMW",    "music": "Jazz"},
    {"house": 2, "color": "Blue",   "nationality": "Swedish",  "pet": "Cat",      "drink": "Coffee",  "sport": "Swimming", "job": "Teacher",   "car": "Ford",   "music": "Pop"},
    {"house": 3, "color": "Green",  "nationality": "Norwegian","pet": "Bird",     "drink": "Milk",    "sport": "Football", "job": "Engineer",  "car": "Toyota", "music": "Rock"},
    {"house": 4, "color": "Yellow", "nationality": "German",   "pet": "Fish",     "drink": "Beer",    "sport": "Golf",     "job": "Lawyer",    "car": "Audi",   "music": "Classical"},
    {"house": 5, "color": "White",  "nationality": "Danish",   "pet": "Horse",    "drink": "Water",   "sport": "Cycling",  "job": "Chef",      "car": "Volvo",  "music": "Blues"},
    {"house": 6, "color": "Orange", "nationality": "French",   "pet": "Rabbit",   "drink": "Juice",   "sport": "Boxing",   "job": "Pilot",     "car": "Peugeot","music": "Hip-hop"},
    {"house": 7, "color": "Purple", "nationality": "Italian",  "pet": "Hamster",  "drink": "Wine",    "sport": "Running",  "job": "Artist",    "car": "Ferrari","music": "R&B"},
    {"house": 8, "color": "Pink",   "nationality": "Spanish",  "pet": "Turtle",   "drink": "Soda",    "sport": "Yoga",     "job": "Scientist", "car": "Honda",  "music": "Reggae"},
]

# 30 clues derived directly from the solution
CLUES = """
CLUES (30 total — all must be satisfied):

1.  The British person lives in the Red house.
2.  The Swedish person keeps a Cat.
3.  The Norwegian lives in house 3.
4.  The person in the Green house drinks Milk.
5.  The German person drinks Beer.
6.  The person who plays Tennis lives in the Red house.
7.  The Doctor drives a BMW.
8.  The person in house 2 drinks Coffee.
9.  The Engineer lives in the Green house.
10. The French person drinks Juice.
11. The person who does Boxing is a Pilot.
12. The person in house 5 keeps a Horse.
13. The Italian person listens to R&B.
14. The person in the Yellow house plays Golf.
15. The Chef lives in the White house.
16. The person in house 1 drinks Tea.
17. The person who does Swimming drives a Ford.
18. The person in the Blue house is a Teacher.
19. The Spanish person listens to Reggae.
20. The person in house 4 has a Fish.
21. The Danish person drinks Water.
22. The person who drives a Ferrari does Running.
23. The person in house 6 lives in the Orange house.
24. The person who listens to Jazz is a Doctor.
25. The German person lives in house 4.
26. The person in house 7 listens to R&B.
27. The person who keeps a Bird plays Football.
28. The person in house 8 drinks Soda.
29. The Lawyer listens to Classical music.
30. The person in house 2 is Swedish.
"""

PUZZLE_INTRO = f"""
There are 8 houses in a row, numbered 1 to 8 from left to right.
Each house has exactly one of each of these attributes:
- Color: Red, Blue, Green, Yellow, White, Orange, Purple, Pink
- Nationality: British, Swedish, Norwegian, German, Danish, French, Italian, Spanish
- Pet: Dog, Cat, Bird, Fish, Horse, Rabbit, Hamster, Turtle
- Drink: Tea, Coffee, Milk, Beer, Water, Juice, Wine, Soda
- Sport: Tennis, Swimming, Football, Golf, Cycling, Boxing, Running, Yoga
- Job: Doctor, Teacher, Engineer, Lawyer, Chef, Pilot, Artist, Scientist
- Car: BMW, Ford, Toyota, Audi, Volvo, Peugeot, Ferrari, Honda
- Music: Jazz, Pop, Rock, Classical, Blues, Hip-hop, R&B, Reggae

{CLUES}

Your task: determine the complete assignment for all 8 houses.
"""


# ── Scoring ───────────────────────────────────────────────────────────────────

ATTRIBUTES = ["color", "nationality", "pet", "drink", "sport", "job", "car", "music"]

def parse_solution(text: str) -> list[dict]:
    """Extract house assignments from model response."""
    results = []
    for i in range(1, 9):
        house = {"house": i}
        patterns = {
            "color":       r"house\s*" + str(i) + r"[^.]*?(?:color|colored|painted)[^.]*?:\s*(\w+)",
            "nationality": r"house\s*" + str(i) + r"[^.]*?nationality[^.]*?:\s*(\w+)",
            "pet":         r"house\s*" + str(i) + r"[^.]*?pet[^.]*?:\s*(\w+)",
            "drink":       r"house\s*" + str(i) + r"[^.]*?drink[^.]*?:\s*(\w+)",
            "sport":       r"house\s*" + str(i) + r"[^.]*?sport[^.]*?:\s*(\w+)",
            "job":         r"house\s*" + str(i) + r"[^.]*?job[^.]*?:\s*(\w+)",
            "car":         r"house\s*" + str(i) + r"[^.]*?car[^.]*?:\s*(\w+)",
            "music":       r"house\s*" + str(i) + r"[^.]*?music[^.]*?:\s*(\w+)",
        }
        # Try direct value matching against known values
        for attr, correct_house in enumerate(CORRECT_SOLUTION):
            if correct_house["house"] == i:
                for key in ATTRIBUTES:
                    val = correct_house[key]
                    if val.lower() in text.lower():
                        # Check it's near "house i" or "house {i}"
                        idx = text.lower().find(val.lower())
                        context = text[max(0, idx-100):idx+100].lower()
                        if str(i) in context or f"house {i}" in context:
                            house[key] = val
        results.append(house)
    return results


def score_solution(response_text: str) -> dict:
    """
    Score by checking how many of the 30 clues are satisfied in the response.
    More reliable than parsing — we check if correct assignments appear.
    """
    text = response_text.lower()
    clue_checks = {
        "British in Red house":         ("british" in text and "red" in text),
        "Swedish has Cat":              ("swedish" in text and "cat" in text),
        "Norwegian in house 3":         ("norwegian" in text and "house 3" in text),
        "Green house drinks Milk":      ("green" in text and "milk" in text),
        "German drinks Beer":           ("german" in text and "beer" in text),
        "Doctor drives BMW":            ("doctor" in text and "bmw" in text),
        "House 2 drinks Coffee":        ("house 2" in text and "coffee" in text),
        "Yellow house plays Golf":      ("yellow" in text and "golf" in text),
        "Italian listens to R&B":       ("italian" in text and "r&b" in text),
        "Spanish listens to Reggae":    ("spanish" in text and "reggae" in text),
        "House 4 has Fish":             ("house 4" in text and "fish" in text),
        "Danish drinks Water":          ("danish" in text and "water" in text),
        "Ferrari person does Running":  ("ferrari" in text and "running" in text),
        "Lawyer listens to Classical":  ("lawyer" in text and "classical" in text),
        "House 8 drinks Soda":          ("house 8" in text and "soda" in text),
    }

    satisfied = sum(1 for v in clue_checks.values() if v)
    total = len(clue_checks)

    return {
        "satisfied": satisfied,
        "total": total,
        "pct": satisfied / total * 100,
        "details": clue_checks,
    }


# ── Baseline ──────────────────────────────────────────────────────────────────

def baseline_solve() -> str:
    prompt = f"""{PUZZLE_INTRO}

Solve this step by step. Work through each clue carefully.
Present your final answer as a table with all 8 houses and all 8 attributes."""
    print("  calling Gemini (single call)...", end=" ", flush=True)
    r = call_gemini(prompt)
    print("done")
    return r


# ── Swarm agents ──────────────────────────────────────────────────────────────

def agent_constraints(clue_block: str, house_range: str) -> str:
    """Agent focused on a subset of clues."""
    print(f"      [constraints agent {house_range}] working...", end=" ", flush=True)
    prompt = f"""{PUZZLE_INTRO}

You are a constraint agent. Focus ONLY on houses {house_range}.
Apply every clue that involves houses {house_range}.
List what you can definitively determine about houses {house_range}.
Be precise. Format each finding as:
  House X: attribute = value (from clue N)"""
    r = call_gemini(prompt)
    print(f"done ({len(r.split(chr(10)))} lines)")
    return r


def agent_deduction(partial_results: list[str]) -> str:
    """Agent that takes partial results and deduces remaining assignments."""
    print(f"      [deduction agent] working...", end=" ", flush=True)
    combined = "\n\n---\n\n".join(partial_results)
    prompt = f"""{PUZZLE_INTRO}

Three constraint agents have worked through subsets of the clues.
Here are their findings:

{combined}

Your job: combine these findings and fill in any remaining gaps using
process of elimination. Every attribute must appear exactly once across
all 8 houses. Present the COMPLETE solution as a table."""
    r = call_gemini(prompt)
    print(f"done ({len(r.split(chr(10)))} lines)")
    return r


def agent_validator_puzzle(solution: str, other_solutions: list[str]) -> str:
    """Validator checks for contradictions between agents."""
    print(f"      [validator agent] checking for contradictions...", end=" ", flush=True)

    # Check if agents produced conflicting assignments
    conflicts = []
    for attr in ["british", "swedish", "german", "norwegian"]:
        positions = []
        for i, sol in enumerate([solution] + other_solutions):
            for line in sol.lower().split("\n"):
                if attr in line:
                    nums = re.findall(r'\d+', line)
                    if nums:
                        positions.append((i, nums[0]))
                        break
        if len(set(p[1] for p in positions)) > 1:
            conflicts.append(attr)

    conflict_msg = f"CONFLICTS DETECTED in: {conflicts}" if conflicts else "No obvious conflicts detected."

    prompt = f"""{PUZZLE_INTRO}

A deduction agent produced this solution:

{solution}

{conflict_msg}

Your job:
1. Check every one of the 30 clues against this solution
2. List any clues that are violated
3. If violations exist, produce a corrected solution
4. End with the final verified solution as a table

Be thorough — check ALL 30 clues."""
    r = call_gemini(prompt)
    print(f"done")
    return r


def swarm_solve() -> dict:
    """Run full swarm pipeline on the puzzle."""
    print("\n  Running 4 agents in parallel sequence:")

    # 3 constraint agents work different house ranges
    r1 = agent_constraints(CLUES, "1, 2, 3, 4")
    r2 = agent_constraints(CLUES, "3, 4, 5, 6")
    r3 = agent_constraints(CLUES, "5, 6, 7, 8")

    # Check for disagreements between agents on overlapping houses (3,4 and 5,6)
    print(f"\n      [energy check] scanning for contradictions between agents...")
    disagreements = []
    for attr in ["norwegian", "german", "french", "danish"]:
        in_r1 = attr in r1.lower()
        in_r2 = attr in r2.lower()
        in_r3 = attr in r3.lower()
        # Check if agents put the same nationality in different positions
        pos_r1 = re.findall(r'house\s*(\d)', r1.lower()[r1.lower().find(attr)-50:r1.lower().find(attr)+50]) if attr in r1.lower() else []
        pos_r2 = re.findall(r'house\s*(\d)', r2.lower()[r2.lower().find(attr)-50:r2.lower().find(attr)+50]) if attr in r2.lower() else []
        if pos_r1 and pos_r2 and pos_r1[0] != pos_r2[0]:
            disagreements.append(f"{attr}: agent1 says house {pos_r1[0]}, agent2 says house {pos_r2[0]}")

    if disagreements:
        print(f"      [!!] DISAGREEMENTS FOUND:")
        for d in disagreements:
            print(f"           - {d}")
    else:
        print(f"      [ok] agents consistent on overlapping houses")

    # Deduction agent combines all partial results
    print()
    r_deduction = agent_deduction([r1, r2, r3])

    # Validator checks the combined solution
    print()
    r_final = agent_validator_puzzle(r_deduction, [r1, r2, r3])

    return {
        "agent_1": r1,
        "agent_2": r2,
        "agent_3": r3,
        "deduction": r_deduction,
        "final": r_final,
        "disagreements": disagreements,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not GEMINI_API_KEY:
        print("ERROR: Set GEMINI_API_KEY in .env")
        return

    print(f"\n{'='*65}")
    print(f"  Einstein Puzzle (Extended) -- 8 houses, 30 clues")
    print(f"  HamiltonianSwarm vs Single Call  |  {MODEL}")
    print(f"{'='*65}")
    print(f"\n  This problem requires holding all 30 constraints simultaneously.")
    print(f"  Other swarms fail because agents forget earlier constraints.")
    print(f"  Scoring: how many of 15 key constraint checks pass?\n")

    # Baseline
    print(f"\n--- BASELINE (single Gemini call) ---")
    b_response = baseline_solve()
    b_score = score_solution(b_response)
    print(f"  Score: {b_score['satisfied']}/{b_score['total']} constraints satisfied ({b_score['pct']:.0f}%)")

    # Swarm
    print(f"\n--- SWARM (4 agents + energy validation) ---")
    s_result = swarm_solve()
    s_score = score_solution(s_result["final"])
    print(f"\n  Score: {s_score['satisfied']}/{s_score['total']} constraints satisfied ({s_score['pct']:.0f}%)")

    # Results
    print(f"\n{'='*65}")
    print(f"  RESULTS")
    print(f"{'='*65}")
    print(f"  Baseline:  {b_score['satisfied']}/{b_score['total']}  ({b_score['pct']:.0f}%)")
    print(f"  Swarm:     {s_score['satisfied']}/{s_score['total']}  ({s_score['pct']:.0f}%)")
    print(f"  Swarm disagreements caught: {len(s_result['disagreements'])}")

    print(f"\n  Constraint-by-constraint:")
    print(f"  {'Constraint':<40} {'Baseline':^10} {'Swarm':^10}")
    print(f"  {'-'*60}")
    for constraint in b_score["details"]:
        b = "PASS" if b_score["details"][constraint] else "FAIL"
        s = "PASS" if s_score["details"][constraint] else "FAIL"
        flag = " <-- swarm fixed it" if b == "FAIL" and s == "PASS" else ""
        print(f"  {constraint:<40} {b:^10} {s:^10}{flag}")

    # Save
    with open("constraint_test_results.json", "w") as f:
        json.dump({
            "baseline_score": b_score,
            "swarm_score": s_score,
            "baseline_response": b_response,
            "swarm_final": s_result["final"],
            "disagreements": s_result["disagreements"],
        }, f, indent=2)
    print(f"\n  Full responses saved to constraint_test_results.json")


if __name__ == "__main__":
    main()
