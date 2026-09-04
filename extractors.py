"""Pull founding year, HQ country and a one-line description out of a page.

Order of trust: JSON-LD (structured, the org said it about itself) beats
regex over visible text. When the page gives two different answers we write
nothing -- an empty cell with a note is worth more than a coin flip.

Each extractor returns (value, method, note). value=None means "not trusted
enough to write", and the note says why.
"""

import json
import re

# enough for the sectors in this dataset; a real run would use pycountry
COUNTRIES = {
    "united states": "United States", "usa": "United States", "u.s.": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "england": "United Kingdom",
    "france": "France", "germany": "Germany", "canada": "Canada", "spain": "Spain",
    "switzerland": "Switzerland", "netherlands": "Netherlands", "australia": "Australia",
    "israel": "Israel", "finland": "Finland", "sweden": "Sweden", "denmark": "Denmark",
    "japan": "Japan", "china": "China", "singapore": "Singapore", "ireland": "Ireland",
    "hong kong": "Hong Kong",
}

ISO2 = {
    "US": "United States", "GB": "United Kingdom", "FR": "France", "DE": "Germany",
    "CA": "Canada", "ES": "Spain", "CH": "Switzerland", "NL": "Netherlands",
    "AU": "Australia", "IL": "Israel", "FI": "Finland", "SE": "Sweden", "DK": "Denmark",
    "JP": "Japan", "CN": "China", "SG": "Singapore", "IE": "Ireland", "HK": "Hong Kong",
}

YEAR_PATTERNS = [
    re.compile(r"\bfounded\s+(?:in\s+)?((?:19|20)\d{2})", re.I),
    re.compile(r"\bestablished\s+(?:in\s+)?((?:19|20)\d{2})", re.I),
    re.compile(r"\bsince\s+((?:19|20)\d{2})", re.I),
    re.compile(r"\bstarted\s+in\s+((?:19|20)\d{2})", re.I),
]


def _jsonld_blocks(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                yield item
                # @graph nesting is common
                for sub in item.get("@graph", []):
                    if isinstance(sub, dict):
                        yield sub


def name_matches(soup, org_name: str) -> bool:
    """Cheap sanity check that we are on the right company's site at all.
    Guards against parked/resold domains and seed rows with a wrong domain."""
    stop = {"inc", "ltd", "llc", "corp", "gmbh", "sas", "ab", "bv", "plc", "ag", "sl",
            "pty", "the", "and", "&", "health", "computing", "systems", "technologies"}
    tokens = [t for t in re.split(r"[^a-z0-9]+", org_name.lower()) if len(t) > 2 and t not in stop]
    if not tokens:
        return True  # nothing distinctive to check against, don't block
    text = soup.get_text(" ", strip=True).lower()
    return any(t in text for t in tokens)


def extract_founded_year(soup):
    for item in _jsonld_blocks(soup):
        fd = item.get("foundingDate")
        if fd:
            m = re.match(r"((?:19|20)\d{2})", str(fd))
            if m:
                return int(m.group(1)), "jsonld", "foundingDate in structured data"

    text = soup.get_text(" ", strip=True)
    years = set()
    for pat in YEAR_PATTERNS:
        years.update(int(y) for y in pat.findall(text))
    years = {y for y in years if 1900 <= y <= 2026}

    if len(years) == 1:
        return years.pop(), "regex", "single 'founded in <year>' style mention"
    if len(years) > 1:
        return None, "regex", f"ambiguous: page mentions {sorted(years)}, not writing"
    return None, None, "no founding year found on page"


def extract_hq_country(soup):
    for item in _jsonld_blocks(soup):
        addr = item.get("address")
        addrs = addr if isinstance(addr, list) else [addr]
        for a in addrs:
            if isinstance(a, dict):
                c = a.get("addressCountry")
                if isinstance(c, dict):
                    c = c.get("name")
                if c:
                    c = str(c).strip()
                    resolved = ISO2.get(c.upper()) or COUNTRIES.get(c.lower()) or c
                    return resolved, "jsonld", "addressCountry in structured data"

    # fall back to the footer only -- an about page body mentioning
    # "offices in France, Germany and Japan" must not become the HQ
    footer = soup.find("footer")
    if footer:
        text = footer.get_text(" ", strip=True).lower()
        hits = {canon for key, canon in COUNTRIES.items()
                if re.search(rf"\b{re.escape(key)}\b", text)}
        if len(hits) == 1:
            return hits.pop(), "footer", "single country name in page footer"
        if len(hits) > 1:
            return None, "footer", f"footer mentions {sorted(hits)}, ambiguous"
    return None, None, "no unambiguous country signal on page"


def extract_description(soup):
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            desc = tag["content"].strip()
            # meta descriptions are self-written marketing but at least they
            # are about the right company; cut to the first sentence
            first = re.split(r"(?<=[.!?])\s+", desc)[0].strip()
            if len(first) >= 40:
                src = "og:description" if "property" in attrs else "meta description"
                return first, src, None
    return None, None, "no usable meta description (would need main-copy heuristics or an LLM)"
