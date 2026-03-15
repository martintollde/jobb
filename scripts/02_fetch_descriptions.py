"""Generate occupation descriptions for LLM scoring and save to data/descriptions.json."""

import json
import os
import sys
import time

import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

DESCRIPTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "descriptions.json")
OCCUPATIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "occupations.csv")

MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 20
SLEEP_BETWEEN = 0.2  # seconds between individual calls


def load_existing() -> dict:
    """Load existing descriptions (for incremental runs)."""
    if os.path.exists(DESCRIPTIONS_PATH):
        with open(DESCRIPTIONS_PATH, "r") as f:
            return json.load(f)
    return {}


def save(descriptions: dict):
    """Save descriptions to JSON."""
    with open(DESCRIPTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(descriptions, f, ensure_ascii=False, indent=2)


def generate_description(client: Anthropic, row: pd.Series) -> str:
    """Generate a task description for one occupation via Claude API."""
    prompt = (
        f'Describe the main tasks and daily work of a Swedish "{row.occupation_name_sv}" '
        f"({row.occupation_name_en}, SSYK code {row.ssyk_code}). "
        f"2-3 sentences. Focus on what they actually do, what tools they use, "
        f"and whether their work is primarily digital or physical."
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def main():
    client = Anthropic()
    df = pd.read_csv(OCCUPATIONS_PATH, dtype={"ssyk_code": str})
    descriptions = load_existing()

    # Filter to occupations not yet described
    todo = df[~df.ssyk_code.isin(descriptions)]
    total = len(df)
    already_done = total - len(todo)

    if len(todo) == 0:
        print(f"All {total} occupations already have descriptions. Nothing to do.")
        return

    print(f"Generating descriptions: {already_done}/{total} already done, {len(todo)} remaining")

    for i, (_, row) in enumerate(todo.iterrows()):
        try:
            desc = generate_description(client, row)
            descriptions[row.ssyk_code] = {
                "ssyk_code": row.ssyk_code,
                "name_sv": row.occupation_name_sv,
                "name_en": row.occupation_name_en,
                "description": desc,
            }
        except Exception as e:
            print(f"  ERROR on {row.ssyk_code} ({row.occupation_name_sv}): {e}")
            # Save progress and continue
            save(descriptions)
            continue

        done = already_done + i + 1
        if (i + 1) % BATCH_SIZE == 0:
            save(descriptions)
            print(f"  Described {done}/{total} occupations (checkpoint saved)")
            time.sleep(1)  # extra pause between batches
        elif (i + 1) % 5 == 0:
            print(f"  Described {done}/{total}...")

        time.sleep(SLEEP_BETWEEN)

    save(descriptions)
    print(f"\nDone. {len(descriptions)}/{total} descriptions saved to {DESCRIPTIONS_PATH}")


if __name__ == "__main__":
    main()
