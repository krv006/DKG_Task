# Seed organisation enrichment

## What I built

A small three-layer pipeline: `fetcher.py` (HTTP with explicit failure statuses),
`extractors.py` (field extraction with a refuse-when-ambiguous rule), `enrich.py`
(record selection + orchestration + JSONL output). It enriches 12 deliberately
chosen records from `data/seed_organizations.csv` with founding year, HQ country
and a one-line description, each field carrying its own `source_url` and
`retrieved_at`. Output: `output/enriched_organizations_<run date>.jsonl`. Run
with `python enrich.py` (needs `requests`, `beautifulsoup4`, `selenium` +
Chrome); `python test_extractors.py` runs the extraction-rule tests.

Failure handling is in `fetcher.py`: timeouts and 5xx retry with backoff, 429
honours `Retry-After` (capped at 30s), 404/403 are not retried, and a 200 that
comes back as a JS shell gets one recovery attempt through headless Chrome
before being declared `empty_page`. `requests` stays the primary transport
because Selenium cannot see HTTP status codes at all.

## Which 12 and why

Not a random pick — the six empty rows (highest value per fetch), two duplicate
pairs whose copies contradict each other (D-Wave 2025 vs 1999; Owkin US vs
France), and four rows whose existing values looked wrong (Rigetti "founded
2024", Xanadu "2025", Pasqal and Terra Quantum marked "United States" with
French/Swiss cities). Reasons are in the code (`PICKS` in `enrich.py`) and in
each output record (`why_picked`).

## What I noticed about the data

- At least 6 duplicate pairs sharing a domain, with conflicting values between copies.
- `hq_country` looks like it was defaulted to "United States" by the previous
  pipeline whenever it was unsure — Massy, Espoo, Stockholm, St. Gallen rows all say US.
- Several `founded_year` values (2024/2025 for companies founded ~2013) look like
  a "year first seen" leaking into "year founded".
- `benevolent.com` is probably the wrong domain entirely (SSL failure; they were on .ai).
- `exscientia.ai` still resolves but the page no longer mentions Exscientia
  (acquired by Recursion) — the name-on-page check refused it.

## Where I refused to write a value

Null + note instead of a guess whenever: the page gave two different founding
years (Rigetti mentions 2003 and 2005), the footer named more than one country,
the org's name did not appear on the fetched page (resold/changed domain), or
nothing could be fetched at all (Ro is behind a 403 bot wall). 12 records were
fetched; 8 got at least one trusted field, 3 got nothing, and I consider all
of those correct outcomes, not failures.

## What I deliberately did not do

- No LLM extraction: regex + JSON-LD is deterministic, explainable in review,
  and needs no key. The description field suffers most from this (see below).
- No deduplication of the seed — the task asks for enrichment; dedup decisions
  (which copy survives) deserve their own pass.
- No crawling beyond homepage/about (max 3 URLs per org) — bounded politeness
  beats coverage at this scale.

## Least happy with

The description field. It comes from `og:description`/meta, which is
self-written marketing and sometimes navigational ("Learn about...", "Discover
more about Pasqal...") rather than a factual one-sentence "what they do". The
honest fix is an LLM summarising the page's main copy with the URL kept as
provenance; I ran out of hour before wiring that in.

## What breaks first at 20,000 records

Sequential fetching with a 1s polite delay: ~6h+ of wall time before anything
else hurts. Then, in order: the headless-Chrome fallback (one browser, one page
at a time), the hand-rolled country list, and the name-match check (token overlap
is too naive at that scale — it needs proper entity matching). The fix is a
worker pool with per-domain rate limits and a persistent fetch cache; the
per-field provenance format already survives that change.

## If I had more time

LLM-based description + founding-year extraction from main copy, a contact-page
fallback for HQ country, retrying 403s through the browser (Ro would likely
pass), and a confidence field per value.

## Tooling disclosure

An AI coding assistant was used as a pair-programmer: it drafted the module skeletons
and this README from my direction; selection of the 12 records, trust rules
(what not to write), and the requests-primary/Selenium-fallback split were
decisions made in that conversation. All code was reviewed and run by me.
