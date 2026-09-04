"""Enrich 12 records from seed_organizations.csv with founding year,
HQ country and a one-line description, from the org's own website.

Run:  python enrich.py
Out:  output/enriched_organizations.jsonl  (one record per line,
      every field carries its own source_url + retrieved_at)
"""

import csv
import json
import time

import requests

from fetcher import fetch
from extractors import (extract_description, extract_founded_year,
                        extract_hq_country, name_matches)

SEED = "data/seed_organizations.csv"
OUT = "output/enriched_organizations.jsonl"

# Not a random 12. Picked to cover the failure modes I saw in the seed:
# the six empty rows (highest value per fetch), two duplicate pairs whose
# copies contradict each other, and rows where the existing value looks wrong.
PICKS = {
    "ORG-0049": "row is empty",
    "ORG-0050": "row is empty; company was acquired by Recursion, site may be gone",
    "ORG-0051": "row is empty; benevolent.com looks like the wrong domain (they used .ai)",
    "ORG-0052": "row is empty",
    "ORG-0053": "row is empty",
    "ORG-0054": "row is empty",
    "ORG-0005": "duplicate of ORG-0042 with conflicting founded_year (2025 vs 1999)",
    "ORG-0039": "duplicate of ORG-0046 with conflicting hq_country (US vs France)",
    "ORG-0002": "founded_year 2024 implausible for Rigetti",
    "ORG-0006": "founded_year 2025 implausible for Xanadu",
    "ORG-0011": "hq_country 'United States' but city is Massy (France)",
    "ORG-0015": "hq_country 'United States' but St. Gallen + .swiss domain say Switzerland",
}

POLITE_DELAY = 1.0  # seconds between orgs; we are hitting company sites, not an API


def field(value, source_url, retrieved_at, method, note):
    return {"value": value, "source_url": source_url if value is not None else None,
            "retrieved_at": retrieved_at, "method": method, "note": note}


def candidate_urls(row):
    urls = []
    if row["source_url"]:
        urls.append(row["source_url"])
    home = f"https://{row['domain']}/"
    if home not in urls:
        urls.append(home)
    urls.append(f"https://{row['domain']}/about")
    return urls


def enrich_one(row, session):
    out = {
        "record_id": row["record_id"],
        "organization_name": row["organization_name"],
        "domain": row["domain"],
        "why_picked": PICKS[row["record_id"]],
        "founded_year": None,
        "hq_country": None,
        "description": None,
        "fetch_log": [],
    }

    for url in candidate_urls(row):
        result = fetch(url, session)
        out["fetch_log"].append({"url": url, "status": result.status, "note": result.note})
        if result.status != "ok":
            continue

        if not name_matches(result.soup, row["organization_name"]):
            out["fetch_log"][-1]["note"] = "page loads but org name not on it -- wrong or resold domain, not trusting"
            continue

        for key, extractor in (("founded_year", extract_founded_year),
                               ("hq_country", extract_hq_country),
                               ("description", extract_description)):
            if out[key] and out[key]["value"] is not None:
                continue  # already have it from an earlier page
            value, method, note = extractor(result.soup)
            out[key] = field(value, result.url, result.retrieved_at, method, note)

        if all(out[k] and out[k]["value"] is not None
               for k in ("founded_year", "hq_country", "description")):
            break  # no reason to hit more pages

    # rows where every fetch failed: record that explicitly instead of nulls with no story
    for key in ("founded_year", "hq_country", "description"):
        if out[key] is None:
            out[key] = field(None, None, None, None, "no page could be fetched and trusted")
    return out


def main():
    with open(SEED, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["record_id"] in PICKS]
    assert len(rows) == len(PICKS), "seed file changed under us?"

    session = requests.Session()
    enriched = []
    for row in rows:
        print(f"{row['record_id']}  {row['organization_name']}")
        rec = enrich_one(row, session)
        for k in ("founded_year", "hq_country", "description"):
            v = rec[k]["value"]
            print(f"    {k}: {v if v is not None else '-- (' + str(rec[k]['note']) + ')'}")
        enriched.append(rec)
        time.sleep(POLITE_DELAY)

    with open(OUT, "w", encoding="utf-8") as f:
        for rec in enriched:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(enriched)} records to {OUT}")


if __name__ == "__main__":
    main()
