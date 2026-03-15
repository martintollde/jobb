# Swedish AI Exposure of the Labour Market
## CLAUDE.md - Project Brief for Claude Code

> Inspired by [karpathy/jobs](https://github.com/karpathy/jobs) — replicated for the Swedish labour market using open government data.
> Goal: interactive treemap of ~400 Swedish occupations scored 0–10 on AI exposure, weighted by employment size.

---

## Project structure

```
swedish-jobs/
├── CLAUDE.md                  ← this file
├── .env                       ← ANTHROPIC_API_KEY (never commit)
├── .gitignore
├── pyproject.toml
├── data/
│   ├── occupations.csv        ← master list with employment, salary, category
│   ├── descriptions.json      ← text descriptions per occupation (for scoring)
│   └── scores.json            ← AI exposure scores + rationale
├── site/
│   ├── index.html             ← interactive treemap
│   └── data.json              ← merged payload for frontend
└── scripts/
    ├── 01_fetch_scb.py        ← pull occupation + employment data from SCB API
    ├── 02_fetch_descriptions.py ← get occupation descriptions (ISCO-08 / AF)
    ├── 03_score.py            ← score each occupation via Claude API
    ├── 04_build_site_data.py  ← merge CSV + scores → site/data.json
    └── utils.py               ← shared helpers
```

---

## Data sources

### Primary: SCB PxWeb API
- **Base URL:** `https://api.scb.se/OV0104/v1/doris/en/ssd/`
- **No API key required.** CC0 license — free to use without attribution requirement.
- **Rate limit:** max 10 requests per 10-second window per IP.
- **Employment by occupation:** table `AM/AM0208/AM0208A/YREG100`
  - Variable: `Yrke2012` = SSYK 2012 code (4-digit), `ContentsCode` = number of employed
  - Filter to most recent year available
- **Salary by occupation:** table `AM/AM0208/AM0208H/YREG80`
  - Returns median monthly salary by SSYK code
- **Explore tables interactively:** `https://www.statistikdatabasen.scb.se/pxweb/en/ssd/`

PxWeb API pattern:
```python
import requests, json

BASE = "https://api.scb.se/OV0104/v1/doris/en/ssd/"
table = "AM/AM0208/AM0208A/YREG100"

# Step 1: GET metadata
meta = requests.get(BASE + table).json()

# Step 2: POST query with filters
query = {
    "query": [
        {"code": "Yrke2012", "selection": {"filter": "all", "values": ["*"]}},
        {"code": "ContentsCode", "selection": {"filter": "item", "values": ["AM0208B2"]}},
        {"code": "Tid", "selection": {"filter": "top", "values": ["1"]}}  # latest year
    ],
    "response": {"format": "json"}
}
result = requests.post(BASE + table, json=query).json()
```

### Secondary: Arbetsförmedlingen Taxonomy API
- **Base URL:** `https://taxonomy.api.jobtechdev.se/v1/taxonomy/`
- **No API key required.**
- Fetch SSYK structure: `GET /taxonomy/occupation-name?offset=0&limit=500`
- Returns: `concept_id`, `preferred_label` (Swedish name), `ssyk_code_2012`
- Documentation: `https://jobtechdev.se/en/products/jobtech-taxonomy`

### Occupation descriptions (for LLM scoring)
Two strategies — try in order:
1. **ISCO-08 group definitions** from ILO (public domain). Fetch the 4-digit ISCO group matching each SSYK code via the SSYK→ISCO crosswalk published by SCB.
   - Crosswalk file: `https://www.scb.se/contentassets/...` (search SCB for "SSYK ISCO conversion key")
   - ILO ISCO descriptions: `https://www.ilo.org/public/english/bureau/stat/isco/isco08/`
2. **Fallback:** Generate a brief Swedish-language task description from the occupation title using Claude itself (cheap, fast, good enough for scoring purposes).

---

## Step-by-step scripts

### 01_fetch_scb.py
**Goal:** produce `data/occupations.csv`

Columns needed:
```
ssyk_code, occupation_name_sv, occupation_name_en, category_1digit, category_2digit,
employment_count, median_monthly_salary_sek, year
```

Logic:
1. Fetch SSYK taxonomy from AF Taxonomy API → get all 4-digit occupation names in Swedish
2. Fetch employment counts from SCB table `AM0208A/YREG100`
3. Fetch salary data from SCB table `AM0208H/YREG80`
4. Join on SSYK code
5. Map 1-digit SSYK group to category label (see category map below)
6. Save to `data/occupations.csv`

SSYK 2012 major groups (1-digit):
```python
CATEGORIES = {
    "1": "Chefer",           # Managers
    "2": "Specialister",     # Professionals
    "3": "Tekniker",         # Technicians & associate professionals
    "4": "Kontorspersonal",  # Clerical support
    "5": "Service & handel", # Service & sales
    "6": "Jordbruk",         # Skilled agricultural
    "7": "Hantverkare",      # Craft & trades
    "8": "Maskinoperatörer", # Plant & machine operators
    "9": "Basyrken",         # Elementary occupations
}
```

### 02_fetch_descriptions.py
**Goal:** produce `data/descriptions.json`

Format:
```json
{
  "3141": {
    "ssyk_code": "3141",
    "name_sv": "Ingenjörer och tekniker inom kemi och biologi",
    "description": "..."
  }
}
```

Logic:
1. For each occupation in occupations.csv, try to find ISCO-08 description via crosswalk
2. If not found, call Claude API with prompt:
   ```
   Describe the main tasks and daily work of a Swedish "{occupation_name_sv}" 
   (SSYK code {code}). 2–3 sentences. Focus on what they actually do, 
   what tools they use, and whether their work is primarily digital or physical.
   ```
3. Cache results — never re-fetch if already in descriptions.json
4. Rate limit: 5 req/sec to Claude API

### 03_score.py
**Goal:** produce `data/scores.json`

Uses the Anthropic Python SDK. Read API key from `.env` via `python-dotenv`.

```python
from anthropic import Anthropic
client = Anthropic()  # reads ANTHROPIC_API_KEY from env
```

Model: `claude-sonnet-4-6` (cost-efficient for batch scoring)

Scoring prompt (send one occupation at a time):
```
You are scoring occupations for AI exposure on a 0–10 scale.

AI Exposure measures how much AI will reshape this occupation — both direct 
automation (AI doing the work) and indirect effects (AI making workers so 
productive that fewer are needed).

Key signal: if the job can be done entirely from a home office on a computer, 
AI exposure is inherently high. Jobs requiring physical presence, manual skill, 
or real-time human interaction have a natural barrier.

Calibration:
- 0–1: Roofers, janitors, construction laborers
- 2–3: Electricians, plumbers, care assistants, firefighters  
- 4–5: Registered nurses, retail workers, physicians
- 6–7: Teachers, managers, accountants, engineers
- 8–9: Software developers, paralegals, data analysts, editors
- 10: Medical transcriptionists, data entry clerks

Occupation: {name_sv} ({name_en if available})
Description: {description}
SSYK code: {ssyk_code}

Respond with JSON only:
{
  "score": <number 0-10, one decimal>,
  "rationale": "<2 sentences in English explaining the score>"
}
```

Output format `data/scores.json`:
```json
{
  "3141": {
    "score": 6.5,
    "rationale": "..."
  }
}
```

Processing:
- Load existing scores.json, skip already-scored occupations
- Process in batches of 20, sleep 1s between batches
- Save after every 20 occupations (checkpoint)
- Log progress: `Scored 45/412 occupations...`

### 04_build_site_data.py
**Goal:** produce `site/data.json` — merged payload for frontend

Format (mirror karpathy's structure):
```json
[
  {
    "name": "Systemutvecklare och programmerare",
    "name_en": "Software developers",
    "ssyk": "2512",
    "category": "Specialister",
    "employment": 87400,
    "salary_median": 52300,
    "score": 8.5,
    "rationale": "...",
    "salary_display": "52 300 kr/mån"
  }
]
```

---

## Frontend (site/index.html)

Single self-contained HTML file. Use D3.js treemap (same as karpathy).

Layout:
- **Area** = employment count
- **Color** = AI exposure score (green #2ecc71 → yellow #f39c12 → red #e74c3c)
- **Group by** SSYK 1-digit category (major group)
- **Hover tooltip** shows: occupation name (SV + EN), employment, salary, score, rationale

Header stats to display:
- Total occupations counted
- Total employment covered
- Weighted average AI exposure score
- % of employment in high-exposure jobs (score ≥ 7)

Filters (nice to have, build last):
- Slider: filter by exposure score range
- Toggle: sort by employment vs. alphabetical within groups

Swedish UI labels:
```
"AI-exponering" = AI exposure
"Sysselsatta" = Employed
"Medianlön" = Median salary  
"Yrkesgrupp" = Occupation group
"Visa alla" = Show all
```

---

## Environment setup

```bash
# Create project
mkdir swedish-jobs && cd swedish-jobs
uv init
uv add anthropic requests python-dotenv pandas

# .env
echo "ANTHROPIC_API_KEY=your_key_here" > .env
echo ".env" >> .gitignore
```

---

## Execution order

```bash
uv run python scripts/01_fetch_scb.py      # ~2 min, no API cost
uv run python scripts/02_fetch_descriptions.py  # ~5 min, low API cost
uv run python scripts/03_score.py          # ~15 min, main API cost (~400 calls)
uv run python scripts/04_build_site_data.py     # instant

# Preview locally
cd site && python -m http.server 8000
```

---

## Error handling conventions

- All HTTP calls: wrap in try/except, retry up to 3x with exponential backoff
- SCB API returns HTTP 403 if rate limit hit — add `time.sleep(1)` between calls
- If SCB table structure has changed, print the metadata and halt with a clear message
- All intermediate outputs are idempotent — re-running scripts should not duplicate data

---

## Potential extensions (post-MVP)

1. **Regional breakdown** — SCB has employment by county (län). Add a county toggle to the treemap.
2. **AF labour market outlook** — Arbetsförmedlingen publishes 5-year shortage/surplus forecasts by occupation. Overlay this as a second dimension: *high AI exposure + growing demand* vs *high AI exposure + shrinking demand*. This is the most analytically interesting addition vs. Karpathy's version.
3. **Time series** — SCB data goes back years. Show how occupation sizes have already shifted.
4. **Gender dimension** — SCB has employment by gender per occupation. Flag heavily female-dominated occupations with high AI exposure (care workers, admin) — a policy-relevant angle.
5. **Deploy** — GitHub Pages works fine for a static site. Just push `site/` to `gh-pages` branch.

---

## Notes for Claude Code

- **Start with `01_fetch_scb.py`** and verify you can get real data before proceeding
- The SCB PxWeb API requires a POST with a JSON query body — GET alone only returns metadata
- SSYK codes in SCB data may include leading zeros — normalize to string, not int
- Some occupations will have suppressed employment data (too few workers) — handle gracefully, set employment to `null` and exclude from treemap area calculation
- The AF Taxonomy API is the easiest way to get Swedish occupation names — use it first
- Run `03_score.py` overnight if scoring all ~400 occupations; it takes time and uses API credits
- Keep `data/` files in git — they're the expensive-to-produce artifacts
