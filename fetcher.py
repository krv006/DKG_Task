import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

import renderer
from renderer import Page

TIMEOUT = 8
MAX_RETRIES = 3
BACKOFF_BASE = 2
MIN_TEXT_CHARS = 400

HEADERS = {
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


def fetch(url: str, session: requests.Session, timeout: int = TIMEOUT) -> FetchResult:
    last_note = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        except requests.Timeout:
            last_note = f"timeout after {timeout}s (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue
        except requests.RequestException as e:
            last_note = f"{type(e).__name__} (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue

        if resp.status_code == 429:
            wait = min(int(resp.headers.get("Retry-After", BACKOFF_BASE ** (attempt + 1))), 30)
            last_note = f"429, waited {wait}s (attempt {attempt + 1})"
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            last_note = f"HTTP {resp.status_code} (attempt {attempt + 1})"
            time.sleep(BACKOFF_BASE ** attempt)
            continue

        if resp.status_code == 403:
            result = _load_in_browser(url, "ok_rendered",
                                      "403 over plain HTTP, retried in a real browser; ")
            if result.status == "ok_rendered":
                return result
            return FetchResult(url, "http_error", _now(),
                               note="HTTP 403 and the browser did not get through either")

        if resp.status_code != 200:
            return FetchResult(url, "http_error", _now(), note=f"HTTP {resp.status_code}")

        return _load_in_browser(str(resp.url), "ok")

    status = "rate_limited" if "429" in last_note else "network_error"
    return FetchResult(url, status, _now(), note=f"gave up after {MAX_RETRIES} attempts: {last_note}")
