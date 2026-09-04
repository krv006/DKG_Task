"""Enrich 12 records from seed_organizations.csv with founding year,
HQ country and a one-line description, from the org's own website.

Run:  python enrich.py
Out:  output/enriched_organizations_<today>.csv -- flat CSV, every field
      carries its own source_url / retrieved_at / method / note columns
"""

import csv
import time
from datetime import date

import requests

import renderer
from fetcher import fetch
from extractors import (extract_description, extract_founded_year,
                        extract_hq_country, name_matches)

SEED = "data/seed_organizations.csv"
OUT = f"output/enriched_organizations_{date.today().isoformat()}.csv"

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

POLITE_DELAY = 1.0   # seconds between orgs; we are hitting company sites, not an API
MAX_URLS_PER_ORG = 7 # bounded politeness beats coverage at this scale

# last-resort source when the live site is walled off or resold: the Wayback
# Machine copy of the org's own pages. Still first-party content; the
# provenance URL points at the snapshot so a reviewer can see what was read.
WAYBACK_YEAR = 2024  # roughly when the seed data was current

FIELDS = ("founded_year", "hq_country", "description")

EXTRACTORS = {
    "founded_year": extract_founded_year,
    "hq_country": extract_hq_country,
    "description": extract_description,
}


def field(value, source_url, retrieved_at, method, note):
    return {"value": value, "source_url": source_url if value is not None else None,
            "retrieved_at": retrieved_at, "method": method, "note": note}


def candidate_urls(row):
    urls = []
    if row["source_url"]:
        urls.append(row["source_url"])
    # common about-page spellings; terraquantum.swiss 404s /about but serves
    # /company, and the contact page is where the HQ address usually lives
    for path in ("", "about", "about-us", "company", "contact"):
        u = f"https://{row['domain']}/{path}" if path else f"https://{row['domain']}/"
        if u not in urls:
            urls.append(u)
    # apex domains with broken TLS sometimes only serve the www host
    if not row["domain"].startswith("www."):
        urls.append(f"https://www.{row['domain']}/")
    return urls[:MAX_URLS_PER_ORG]


def wayback_urls(row):
    return [f"https://web.archive.org/web/{WAYBACK_YEAR}/https://{row['domain']}/{path}"
            for path in ("", "about")]


def is_complete(out):
    return all(out[k] and out[k]["value"] is not None for k in FIELDS)


def try_url(out, row, url, session):
    result = fetch(url, session)
    entry = {"url": url, "status": result.status, "note": result.note}
    out["fetch_log"].append(entry)
    if result.status not in ("ok", "ok_rendered"):
        return

    if not name_matches(result.page, row["organization_name"], row["domain"]):
        entry["note"] = "page loads but org name not on it -- wrong or resold domain, not trusting"
        return

    for key in FIELDS:
        if out[key] and out[key]["value"] is not None:
            continue  # already have it from an earlier page
        value, method, note = EXTRACTORS[key](result.page)
        out[key] = field(value, result.url, result.retrieved_at, method, note)


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
        if is_complete(out):
            break  # no reason to hit more pages
        try_url(out, row, url, session)

    # still missing something? the org's own site said all it will say --
    # ask the Wayback Machine for the same site before giving up
    if not is_complete(out):
        for url in wayback_urls(row):
            if is_complete(out):
                break
            try_url(out, row, url, session)

    # rows where every fetch failed: record that explicitly instead of nulls with no story
    for key in FIELDS:
        if out[key] is None:
            out[key] = field(None, None, None, None, "no page could be fetched and trusted")
    return out


def to_csv_row(rec):
    row = {k: rec[k] for k in ("record_id", "organization_name", "domain", "why_picked")}
    for key in FIELDS:
        f = rec[key]
        row[key] = f["value"]
        row[f"{key}_source_url"] = f["source_url"]
        row[f"{key}_retrieved_at"] = f["retrieved_at"]
        row[f"{key}_method"] = f["method"]
        row[f"{key}_note"] = f["note"]
    row["fetch_summary"] = "; ".join(
        f"{e['url']} -> {e['status']}" + (f" ({e['note']})" if e["note"] else "")
        for e in rec["fetch_log"])
    return row


def main():
    with open(SEED, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["record_id"] in PICKS]
    assert len(rows) == len(PICKS), "seed file changed under us?"

    session = requests.Session()
    enriched = []
    try:
        for row in rows:
            print(f"{row['record_id']}  {row['organization_name']}", flush=True)
            rec = enrich_one(row, session)
            for k in FIELDS:
                v = rec[k]["value"]
                print(f"    {k}: {v if v is not None else '-- (' + str(rec[k]['note']) + ')'}", flush=True)
            enriched.append(rec)
            time.sleep(POLITE_DELAY)
    finally:
        renderer.shutdown()

    csv_rows = [to_csv_row(rec) for rec in enriched]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nwrote {len(csv_rows)} records to {OUT}")


if __name__ == "__main__":
    main()
