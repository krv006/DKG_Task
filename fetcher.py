"""HTTP layer. Every failure mode ends up as a FetchResult with a status,
so the caller never has to catch anything itself.

Statuses:
    ok            - 200 with a body that looks like a real page
    ok_rendered   - 200 was a JS shell, recovered by rendering in headless Chrome
    empty_page    - 200 with nothing useful even after rendering (parked domain etc.)
    http_error    - 4xx that is not worth retrying (404, 403, ...)
    rate_limited  - 429 that survived all retries
    network_error - timeout / DNS / connection failure after retries
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import renderer

TIMEOUT = 8          # seconds; slow corporate sites exist but 8s catches most
MAX_RETRIES = 3
BACKOFF_BASE = 2     # 2s, 4s, 8s
MIN_TEXT_CHARS = 400 # below this a 200 is probably a JS shell or a parked page

HEADERS = {
    # honest UA; some sites 403 the default python-requests one
    "User-Agent": "Mozilla/5.0 (compatible; dkg-enrichment/0.1; research use)"
}


@dataclass
class FetchResult:
    url: str
    status: str
    retrieved_at: str
    html: str = ""
    soup: BeautifulSoup = None
    note: str = ""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, session: requests.Session) -> FetchResult:
    last_note = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.Timeout:
            last_note = f"timeout after {TIMEOUT}s (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue
        except requests.RequestException as e:
            # DNS failure, connection refused, TLS errors. Retrying DNS rarely
            # helps but costs little; everything else here is transient enough.
            last_note = f"{type(e).__name__} (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue

        if resp.status_code == 429:
            # respect Retry-After if the server sent one, but cap it --
            # this is a 12-record run, not a crawler that can afford to wait 5 min
            wait = min(int(resp.headers.get("Retry-After", BACKOFF_BASE ** (attempt + 1))), 30)
            last_note = f"429, waited {wait}s (attempt {attempt + 1})"
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            last_note = f"HTTP {resp.status_code} (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue

        if resp.status_code != 200:
            # 404/403/410: retrying will not change the answer
            return FetchResult(url, "http_error", _now(), note=f"HTTP {resp.status_code}")

        # parse from bytes: requests guesses ISO-8859-1 when the header has no
        # charset, which mangled UTF-8 quotes; bs4 reads the <meta charset> itself
        soup = BeautifulSoup(resp.content, "html.parser")
        visible = soup.get_text(" ", strip=True)
        if len(visible) < MIN_TEXT_CHARS:
            # a 200 with no text is usually a JS-only site; give the browser one shot
            html, note = renderer.render(str(resp.url))
            if html:
                soup = BeautifulSoup(html, "html.parser")
                if len(soup.get_text(" ", strip=True)) >= MIN_TEXT_CHARS:
                    return FetchResult(str(resp.url), "ok_rendered", _now(), html, soup, note=note)
            return FetchResult(url, "empty_page", _now(), resp.text, soup,
                               note=f"200 but only {len(visible)} chars of text, "
                                    f"rendering did not help ({note})")

        return FetchResult(str(resp.url), "ok", _now(), resp.text, soup)

    status = "rate_limited" if "429" in last_note else "network_error"
    return FetchResult(url, status, _now(), note=f"gave up after {MAX_RETRIES} attempts: {last_note}")
