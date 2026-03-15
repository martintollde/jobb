"""Score each occupation for AI exposure (0-10) via Claude API."""

import json
import os
import re
import time

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

DESCRIPTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "descriptions.json")
SCORES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scores.json")

MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 20
SLEEP_BETWEEN = 0.2

SCORING_PROMPT = """You are scoring occupations for AI exposure on a 0-10 scale.

AI Exposure measures how much AI will reshape this occupation — both direct automation (AI doing the work) and indirect effects (AI making workers so productive that fewer are needed).

Key signal: if the job can be done entirely from a home office on a computer, AI exposure is inherently high. Jobs requiring physical presence, manual skill, or real-time human interaction have a natural barrier.

Calibration:
- 0-1: Roofers, janitors, construction laborers
- 2-3: Electricians, plumbers, care assistants, firefighters
- 4-5: Registered nurses, retail workers, physicians
- 6-7: Teachers, managers, accountants, engineers
- 8-9: Software developers, paralegals, data analysts, editors
- 10: Medical transcriptionists, data entry clerks

Occupation: {name_sv} ({name_en})
Description: {description}
SSYK code: {ssyk_code}

Respond with JSON only:
{{"score": <number 0-10, one decimal>, "rationale": "<2 meningar på svenska som förklarar poängen>"}}"""


def load_existing_scores() -> dict:
    if os.path.exists(SCORES_PATH):
        with open(SCORES_PATH, "r") as f:
            return json.load(f)
    return {}


def save_scores(scores: dict):
    with open(SCORES_PATH, "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)


def parse_score_response(text: str) -> dict:
    """Parse JSON from Claude's response, handling markdown code blocks."""
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def score_occupation(client: Anthropic, occ: dict) -> dict:
    prompt = SCORING_PROMPT.format(
        name_sv=occ["name_sv"],
        name_en=occ.get("name_en", ""),
        description=occ["description"],
        ssyk_code=occ["ssyk_code"],
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_score_response(response.content[0].text)


def main():
    client = Anthropic()

    with open(DESCRIPTIONS_PATH, "r") as f:
        descriptions = json.load(f)

    scores = load_existing_scores()
    todo = {k: v for k, v in descriptions.items() if k not in scores}
    total = len(descriptions)
    already_done = total - len(todo)

    if len(todo) == 0:
        print(f"All {total} occupations already scored. Nothing to do.")
        return

    print(f"Scoring occupations: {already_done}/{total} already done, {len(todo)} remaining")

    for i, (code, occ) in enumerate(todo.items()):
        try:
            result = score_occupation(client, occ)
            scores[code] = {
                "score": result["score"],
                "rationale": result["rationale"],
            }
        except Exception as e:
            print(f"  ERROR on {code} ({occ['name_sv']}): {e}")
            save_scores(scores)
            continue

        done = already_done + i + 1
        if (i + 1) % BATCH_SIZE == 0:
            save_scores(scores)
            print(f"  Scored {done}/{total} occupations (checkpoint saved)")
            time.sleep(1)
        elif (i + 1) % 5 == 0:
            print(f"  Scored {done}/{total}...")

        time.sleep(SLEEP_BETWEEN)

    save_scores(scores)
    print(f"\nDone. {len(scores)}/{total} scores saved to {SCORES_PATH}")

    # Quick stats
    vals = [s["score"] for s in scores.values()]
    avg = sum(vals) / len(vals)
    high = sum(1 for v in vals if v >= 7)
    print(f"  Average score: {avg:.1f}")
    print(f"  High exposure (>=7): {high}/{len(vals)} ({100*high/len(vals):.0f}%)")


if __name__ == "__main__":
    main()
