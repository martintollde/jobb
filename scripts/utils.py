"""Shared helpers for SCB API calls."""

import time
import requests

SCB_BASE_SV = "https://api.scb.se/OV0104/v1/doris/sv/ssd/"
SCB_BASE_EN = "https://api.scb.se/OV0104/v1/doris/en/ssd/"

# Rate limit: 10 requests per 10 seconds — we sleep 1s between calls to stay safe.
_last_call_time = 0.0


def _rate_limit():
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_call_time = time.time()


def scb_get(table_path: str, lang: str = "en") -> dict:
    """GET metadata from SCB PxWeb API with retry."""
    base = SCB_BASE_SV if lang == "sv" else SCB_BASE_EN
    url = base + table_path
    for attempt in range(3):
        _rate_limit()
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  Retry {attempt + 1}/3 after {wait}s: {e}")
            time.sleep(wait)


def scb_post(table_path: str, query: dict, lang: str = "en") -> dict:
    """POST query to SCB PxWeb API with retry."""
    base = SCB_BASE_SV if lang == "sv" else SCB_BASE_EN
    url = base + table_path
    for attempt in range(3):
        _rate_limit()
        try:
            resp = requests.post(url, json=query, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  Retry {attempt + 1}/3 after {wait}s: {e}")
            time.sleep(wait)
