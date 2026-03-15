"""Merge occupations.csv + scores.json → site/data.json for the frontend."""

import json
import os

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "site")


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "occupations.csv"), dtype={"ssyk_code": str})

    with open(os.path.join(DATA_DIR, "scores.json"), "r") as f:
        scores = json.load(f)

    with open(os.path.join(DATA_DIR, "descriptions.json"), "r") as f:
        descriptions = json.load(f)

    records = []
    missing_scores = 0
    for _, row in df.iterrows():
        code = row.ssyk_code
        score_data = scores.get(code)
        desc_data = descriptions.get(code)

        if not score_data:
            missing_scores += 1
            continue

        emp = int(row.employment_count) if pd.notna(row.employment_count) else None
        salary = int(row.median_monthly_salary_sek) if pd.notna(row.median_monthly_salary_sek) else None

        records.append({
            "name": row.occupation_name_sv,
            "name_en": row.occupation_name_en,
            "ssyk": code,
            "category": row.category_1digit,
            "category_2digit": row.category_2digit,
            "employment": emp,
            "salary_median": salary,
            "salary_display": f"{salary:,} kr/mån".replace(",", " ") if salary else None,
            "score": score_data["score"],
            "rationale": score_data["rationale"],
            "description": desc_data["description"] if desc_data else None,
        })

    # Sort by score descending for default display order
    records.sort(key=lambda r: r["score"], reverse=True)

    os.makedirs(SITE_DIR, exist_ok=True)
    out_path = os.path.join(SITE_DIR, "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    # Stats
    scored = [r for r in records if r["employment"]]
    total_emp = sum(r["employment"] for r in scored)
    weighted_score = sum(r["score"] * r["employment"] for r in scored) / total_emp if total_emp else 0
    high_exposure = sum(r["employment"] for r in scored if r["score"] >= 7)

    print(f"Built {out_path}")
    print(f"  {len(records)} occupations ({missing_scores} skipped — no score)")
    print(f"  Total employment: {total_emp:,}")
    print(f"  Weighted avg AI exposure: {weighted_score:.1f}")
    print(f"  High exposure (score >= 7): {high_exposure:,} workers ({100*high_exposure/total_emp:.1f}%)")


if __name__ == "__main__":
    main()
