"""Transport layer. requests does the status-code preflight (a browser
cannot see a 429 or a 404), then renderer.py loads the page in headless
Chrome and harvests the DOM. Every failure mode ends up as a FetchResult
with a status, so the caller never has to catch anything itself.

Statuses:
    ok            - 200 and the browser got a page with real text in it
    ok_rendered   - plain HTTP was refused (403 bot wall) but a real browser got through
    empty_page    - 200 but nothing useful even after rendering (parked domain etc.)
    http_error    - 4xx that is not worth retrying (404, 410, ...)
    rate_limited  - 429 that survived all retries
    network_error - timeout / DNS / connection failure after retries
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

import renderer
from renderer import Page

TIMEOUT = 8          # seconds; slow corporate sites exist but 8s catches most
MAX_RETRIES = 3
BACKOFF_BASE = 2     # 2s, 4s, 8s
MIN_TEXT_CHARS = 400 # below this a rendered page is probably parked or an error shell

HEADERS = {
    # honest UA; some sites 403 the default python-requests one
    "User-Agent": "Mozilla/5.0 (compatible; dkg-enrichment/0.1; research use)"
}


@dataclass
class FetchResult:
    url: str
    status: str
    retrieved_at: str
    page: Page = None
    note: str = ""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_in_browser(url, status, extra_note=""):
    page, note = renderer.load(url)
    if page is None:
        return FetchResult(url, "empty_page", _now(), note=f"{extra_note}{note}")
    if len(page.body_text) < MIN_TEXT_CHARS:
        return FetchResult(url, "empty_page", _now(), page,
                           note=f"{extra_note}rendered but only "
                                f"{len(page.body_text)} chars of text (parked or error shell?)")
    return FetchResult(page.url, status, _now(), page, note=extra_note.strip(" ;"))


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

        if resp.status_code == 403:
            # bot walls 403 plain HTTP clients but often let a real browser in
            result = _load_in_browser(url, "ok_rendered",
                                      "403 over plain HTTP, retried in a real browser; ")
            if result.status == "ok_rendered":
                return result
            return FetchResult(url, "http_error", _now(),
                               note="HTTP 403 and the browser did not get through either")

        if resp.status_code != 200:
            # 404/410: retrying will not change the answer
            return FetchResult(url, "http_error", _now(), note=f"HTTP {resp.status_code}")

        return _load_in_browser(str(resp.url), "ok")

    status = "rate_limited" if "429" in last_note else "network_error"
    return FetchResult(url, status, _now(), note=f"gave up after {MAX_RETRIES} attempts: {last_note}")
