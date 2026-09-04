
import json
import re

from renderer import Page

COUNTRIES = {
    "united states": "United States", "usa": "United States", "u.s.": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "england": "United Kingdom",
    "france": "France", "germany": "Germany", "canada": "Canada", "spain": "Spain",
    "switzerland": "Switzerland", "netherlands": "Netherlands", "australia": "Australia",
    "israel": "Israel", "finland": "Finland", "sweden": "Sweden", "denmark": "Denmark",
    "japan": "Japan", "china": "China", "singapore": "Singapore", "ireland": "Ireland",
    "hong kong": "Hong Kong", "italy": "Italy", "belgium": "Belgium",
    "austria": "Austria", "norway": "Norway", "india": "India",
}

# unmistakable HQ cities only -- Cambridge (UK/US) deliberately absent
HQ_CITIES = {
    "massy": "France", "paris": "France", "toronto": "Canada",
    "london": "United Kingdom", "st. gallen": "Switzerland",
    "st gallen": "Switzerland", "barcelona": "Spain",
    "berkeley": "United States", "new york": "United States",
    "boston": "United States", "palo alto": "United States",
    "san francisco": "United States", "amsterdam": "Netherlands",
    "tokyo": "Japan", "tel aviv": "Israel", "helsinki": "Finland",
    "espoo": "Finland", "stockholm": "Sweden", "copenhagen": "Denmark",
    "munich": "Germany", "berlin": "Germany",
}

ISO2 = {
    "US": "United States", "GB": "United Kingdom", "FR": "France", "DE": "Germany",
    "CA": "Canada", "ES": "Spain", "CH": "Switzerland", "NL": "Netherlands",
    "AU": "Australia", "IL": "Israel", "FI": "Finland", "SE": "Sweden", "DK": "Denmark",
    "JP": "Japan", "CN": "China", "SG": "Singapore", "IE": "Ireland", "HK": "Hong Kong",
}

YEAR_PATTERNS = [
    re.compile(r"\bfounded\s+(?:in\s+)?((?:19|20)\d{2})", re.I),
    # "founded in Berkeley, California, in 2013" -- year after an interlude
    re.compile(r"\bfounded[^.\n]{0,60}?\bin\s+((?:19|20)\d{2})", re.I),
    # "In 2019, Pasqal was founded ..."
    re.compile(r"\bin\s+((?:19|20)\d{2})[^.\n]{0,60}?\bfounded\b", re.I),
    re.compile(r"\bestablished\s+(?:in\s+)?((?:19|20)\d{2})", re.I),
    re.compile(r"\best\.?\s+((?:19|20)\d{2})\b", re.I),
    re.compile(r"\bsince\s+((?:19|20)\d{2})", re.I),
    re.compile(r"\bstarted\s+in\s+((?:19|20)\d{2})", re.I),
    re.compile(r"\bcreated\s+in\s+((?:19|20)\d{2})", re.I),
]


def _jsonld_items(page: Page):
    for raw in page.jsonld_raw:
        try:
            data = json.loads(raw or "")
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


def name_matches(page: Page, org_name: str, domain: str = "") -> bool:
    """Cheap sanity check that we are on the right company's site at all.
    Guards against parked/resold domains and seed rows with a wrong domain."""
    stop = {"inc", "ltd", "llc", "corp", "gmbh", "sas", "ab", "bv", "plc", "ag", "sl",
            "pty", "the", "and", "&", "health", "computing", "systems", "technologies"}
    tokens = [t for t in re.split(r"[^a-z0-9]+", org_name.lower()) if len(t) > 2 and t not in stop]
    if not tokens:
        return True  # nothing distinctive to check against, don't block
    text = (page.title + " " + page.body_text).lower()
    if any(t in text for t in tokens):
        return True
    # short brand names ("Ro") produce no usable tokens above; accept the
    # domain label as a whole word instead ("ro" in "Ro | Telehealth ...")
    label = domain.lower().removeprefix("www.").split(".")[0]
    return bool(label) and re.search(rf"\b{re.escape(label)}\b", text) is not None


def extract_founded_year(page: Page):
    for item in _jsonld_items(page):
        fd = item.get("foundingDate")
        if fd:
            m = re.match(r"((?:19|20)\d{2})", str(fd))
            if m:
                return int(m.group(1)), "jsonld", "foundingDate in structured data"

    years = set()
    for pat in YEAR_PATTERNS:
        years.update(int(y) for y in pat.findall(page.body_text))
    years = {y for y in years if 1900 <= y <= 2026}

    if len(years) == 1:
        return years.pop(), "regex", "single 'founded in <year>' style mention"
    if len(years) > 1:
        return None, "regex", f"ambiguous: page mentions {sorted(years)}, not writing"
    return None, None, "no founding year found on page"


def extract_hq_country(page: Page):
    for item in _jsonld_items(page):
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

    # fall back to the footer -- an about page body mentioning
    # "offices in France, Germany and Japan" must not become the HQ.
    # Sites without a <footer> element get the bottom of the page instead,
    # which is where the address block lives in practice.
    footer = page.footer_text or page.body_text[-600:]
    src = "footer" if page.footer_text else "page-bottom"
    if footer.strip():
        text = footer.lower()
        hits = {canon for key, canon in COUNTRIES.items()
                if re.search(rf"\b{re.escape(key)}\b", text)}
        if len(hits) == 1:
            return hits.pop(), src, f"single country name in {src}"
        if len(hits) > 1:
            return None, src, f"{src} mentions {sorted(hits)}, ambiguous"
        # no country spelled out; an unmistakable HQ city is the next best thing
        cities = {canon for city, canon in HQ_CITIES.items()
                  if re.search(rf"\b{re.escape(city)}\b", text)}
        if len(cities) == 1:
            return cities.pop(), src, f"single known HQ city in {src}"

    # an explicit HQ claim in the body copy is trustworthy even outside the footer
    claims = set()
    for chunk in re.findall(r"\b(?:headquartered|based)\s+in\s+([A-Za-z][A-Za-z .,-]{2,40})",
                            page.body_text, re.I):
        low = chunk.lower()
        for key, canon in COUNTRIES.items():
            if re.search(rf"\b{re.escape(key)}\b", low):
                claims.add(canon)
        for city, canon in HQ_CITIES.items():
            if re.search(rf"\b{re.escape(city)}\b", low):
                claims.add(canon)
    if len(claims) == 1:
        return claims.pop(), "body-statement", "'headquartered in ...' claim in body copy"
    if len(claims) > 1:
        return None, "body-statement", f"conflicting HQ claims {sorted(claims)}, ambiguous"
    return None, None, "no unambiguous country signal on page"


def extract_description(page: Page):
    for content, src in ((page.og_description, "og:description"),
                         (page.meta_description, "meta description")):
        desc = (content or "").strip()
        if desc:
            # meta descriptions are self-written marketing but at least they
            # are about the right company; cut to the first sentence
            first = re.split(r"(?<=[.!?])\s+", desc)[0].strip()
            if len(first) >= 40:
                return first, src, None
    return None, None, "no usable meta description (would need main-copy heuristics or an LLM)"
