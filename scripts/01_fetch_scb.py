"""Fetch occupation data from SCB and produce data/occupations.csv."""

import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from utils import scb_get, scb_post

EMPLOYMENT_TABLE = "AM/AM0208/AM0208E/YREG50BAS"
SALARY_TABLE = "AM/AM0110/AM0110A/LoneSpridSektYrk4AN"

CATEGORIES = {
    "0": "Militärt arbete",    # Armed forces
    "1": "Chefer",             # Managers
    "2": "Specialister",       # Professionals
    "3": "Tekniker",           # Technicians & associate professionals
    "4": "Kontorspersonal",    # Clerical support
    "5": "Service & handel",   # Service & sales
    "6": "Jordbruk",           # Skilled agricultural
    "7": "Hantverkare",        # Craft & trades
    "8": "Maskinoperatörer",   # Plant & machine operators
    "9": "Basyrken",           # Elementary occupations
}


def fetch_occupation_names() -> dict[str, dict]:
    """Get SSYK code → {name_sv, name_en} from SCB metadata endpoints."""
    print("Fetching occupation names (Swedish)...")
    meta_sv = scb_get(EMPLOYMENT_TABLE, lang="sv")
    print("Fetching occupation names (English)...")
    meta_en = scb_get(EMPLOYMENT_TABLE, lang="en")

    # Find the Yrke2012 variable in metadata
    sv_values = None
    en_values = None
    for var in meta_sv["variables"]:
        if var["code"] == "Yrke2012":
            sv_values = dict(zip(var["values"], var["valueTexts"]))
            break
    for var in meta_en["variables"]:
        if var["code"] == "Yrke2012":
            en_values = dict(zip(var["values"], var["valueTexts"]))
            break

    if not sv_values or not en_values:
        raise RuntimeError("Could not find Yrke2012 variable in SCB metadata")

    # Aggregate/meta codes to exclude
    EXCLUDE_CODES = {"0000", "0001", "0002"}

    names = {}
    for code in sv_values:
        # Only keep 4-digit occupation codes, skip aggregates
        if len(code) == 4 and code not in EXCLUDE_CODES:
            names[code] = {
                "name_sv": sv_values.get(code, ""),
                "name_en": en_values.get(code, ""),
            }

    print(f"  Found {len(names)} occupation codes")
    return names


def fetch_employment() -> dict[str, int | None]:
    """Fetch employment counts. Sum men + women since no combined code exists."""
    print("Fetching employment data...")
    query = {
        "query": [
            {"code": "Yrke2012", "selection": {"filter": "all", "values": ["*"]}},
            {"code": "ArbetsSektor", "selection": {"filter": "item", "values": ["010"]}},
            {"code": "Kon", "selection": {"filter": "item", "values": ["1", "2"]}},
            {"code": "ContentsCode", "selection": {"filter": "item", "values": ["000006Y5"]}},
            {"code": "Tid", "selection": {"filter": "top", "values": ["1"]}},
        ],
        "response": {"format": "json"},
    }
    result = scb_post(EMPLOYMENT_TABLE, query)

    # Sum men + women per occupation code
    counts: dict[str, int] = {}
    suppressed = 0
    for entry in result["data"]:
        code = entry["key"][0]  # Yrke2012
        if len(code) != 4:
            continue
        val = entry["values"][0]
        if val == ".." or val == "":
            suppressed += 1
            continue
        counts[code] = counts.get(code, 0) + int(val)

    year = result["data"][0]["key"][3] if result["data"] else "unknown"
    print(f"  Got employment for {len(counts)} occupations (year={year}, {suppressed} suppressed values)")
    return counts, year


def fetch_salary() -> dict[str, int | None]:
    """Fetch median monthly salary."""
    print("Fetching salary data...")
    query = {
        "query": [
            {"code": "Yrke2012", "selection": {"filter": "all", "values": ["*"]}},
            {"code": "Sektor", "selection": {"filter": "item", "values": ["0"]}},
            {"code": "Kon", "selection": {"filter": "item", "values": ["1+2"]}},
            {"code": "ContentsCode", "selection": {"filter": "item", "values": ["000007CE"]}},
            {"code": "Tid", "selection": {"filter": "top", "values": ["1"]}},
        ],
        "response": {"format": "json"},
    }
    result = scb_post(SALARY_TABLE, query)

    salaries: dict[str, int | None] = {}
    suppressed = 0
    for entry in result["data"]:
        code = entry["key"][1]  # Yrke2012 (key[0] is Sektor in this table)
        if len(code) != 4:
            continue
        val = entry["values"][0]
        if val == ".." or val == "":
            salaries[code] = None
            suppressed += 1
        else:
            salaries[code] = int(val)

    year = result["data"][0]["key"][3] if result["data"] else "unknown"
    print(f"  Got salary for {len(salaries)} occupations (year={year}, {suppressed} suppressed)")
    return salaries, year


def main():
    names = fetch_occupation_names()
    employment, emp_year = fetch_employment()
    salaries, sal_year = fetch_salary()

    # Build rows — left join from names (all known occupations)
    rows = []
    for code, name_data in sorted(names.items()):
        emp_count = employment.get(code)
        salary = salaries.get(code)
        first_digit = code[0]
        rows.append({
            "ssyk_code": code,
            "occupation_name_sv": name_data["name_sv"],
            "occupation_name_en": name_data["name_en"],
            "category_1digit": CATEGORIES.get(first_digit, "Okänd"),
            "category_2digit": code[:2],
            "employment_count": emp_count,
            "median_monthly_salary_sek": salary,
            "year": emp_year,
        })

    df = pd.DataFrame(rows)

    # Verify
    dupes = df[df.duplicated(subset="ssyk_code")]
    if len(dupes) > 0:
        print(f"WARNING: {len(dupes)} duplicate ssyk_codes found!")

    non_4digit = df[df["ssyk_code"].str.len() != 4]
    if len(non_4digit) > 0:
        print(f"WARNING: {len(non_4digit)} codes are not 4 digits!")

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "occupations.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} occupations to {out_path}")
    print(f"  Employment year: {emp_year}, Salary year: {sal_year}")
    print(f"  With employment data: {df['employment_count'].notna().sum()}")
    print(f"  With salary data: {df['median_monthly_salary_sek'].notna().sum()}")
    print(f"\nFirst 10 rows:")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
