# Seed organisation enrichment

## What I built

A small four-layer pipeline: `fetcher.py` (requests preflight for HTTP status
codes with explicit failure statuses), `renderer.py` (Selenium headless Chrome
loads every page after the JS has run and harvests the DOM into a plain `Page`
object), `extractors.py` (pure functions over `Page` with a
refuse-when-ambiguous rule), `enrich.py` (record selection + orchestration +
CSV output). It enriches 12 deliberately chosen records from
`data/seed_organizations.csv` with founding year, HQ country and a one-line
description, each field carrying its own `source_url` / `retrieved_at` /
`method` / `note` columns. Output: `output/enriched_organizations_<run
date>.csv`. Run with `python enrich.py` (needs `requests`, `selenium` +
Chrome); `python test_extractors.py` runs the extraction-rule tests (no
browser needed -- extractors are pure).

Failure handling is in `fetcher.py`: timeouts and 5xx retry with backoff, 429
honours `Retry-After` (capped at 30s), 404 is not retried, a 403 gets one
attempt through the real browser (bot walls block plain HTTP but often let
Chrome in), and a 200 whose rendered page still has no text is declared
`empty_page`. The split exists because each side is blind to something:
Selenium cannot see HTTP status codes, and requests cannot run the JS that
SPA sites need before they contain anything.

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
- No crawling beyond homepage/about-style pages (max 5 URLs per org) — bounded
  politeness beats coverage at this scale.

## Least happy with

Every successful page is fetched twice: once by requests (the only way to see
a 429/404) and again by the browser (the only way to run the JS). At 12
records that is invisible; it is wasteful by design and the fix (a CDP-level
client that exposes response status from inside the browser session) did not
fit the hour. Runner-up: the description field is `og:description`/meta, which
is self-written marketing and sometimes navigational ("Discover more about
Pasqal...") rather than a factual "what they do" — an LLM summarising the
main copy, URL kept as provenance, is the honest fix.

## What breaks first at 20,000 records

Sequential fetching through one headless Chrome with a 1s polite delay: days
of wall time before anything else hurts. Then, in order: the double fetch per
page (requests + browser), the hand-rolled country list, and the name-match
check (token overlap is too naive at that scale — it needs proper entity
matching). The fix is a pool of browser workers with per-domain rate limits
and a persistent fetch cache; the per-field provenance format already
survives that change.

## If I had more time

LLM-based description + founding-year extraction from main copy, a
contact-page fallback for HQ country, and a confidence field per value.

## Tooling disclosure

An AI coding assistant was used as a pair-programmer: it drafted the module
skeletons and parts of this README from my direction; selection of the 12
records, trust rules (what not to write), and the requests-primary/
Selenium-fallback split were my decisions. All code was reviewed and run by me.
