"""Browser layer. Selenium loads every page and harvests the DOM after the
JS has run, so SPA sites (xanadu.ai, ceracare.co.uk) parse the same as
static ones. The one thing a browser cannot see is the HTTP status code --
that stays fetcher.py's job.

Extraction never touches the driver directly: load() harvests everything
extractors need into a plain Page object in one execute_script call, which
keeps the extractors pure functions and testable without a browser.
"""

import time
from dataclasses import dataclass, field

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException

PAGE_LOAD_TIMEOUT = 15  # seconds per page before we give up on the load event
HYDRATION_WAIT = 8      # extra budget for the JS to actually fill the DOM
HYDRATION_MIN_CHARS = 400

_HARVEST_JS = """
return {
  title:  document.title || "",
  body:   document.body ? document.body.innerText : "",
  footer: (function(f){ return f ? f.innerText : ""; })(document.querySelector("footer")),
  jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
               .map(function(s){ return s.textContent; }),
  og:     (function(m){ return m ? m.content : ""; })(document.querySelector('meta[property="og:description"]')),
  meta:   (function(m){ return m ? m.content : ""; })(document.querySelector('meta[name="description"]')),
};
"""

_driver = None


@dataclass
class Page:
    url: str = ""
    title: str = ""
    body_text: str = ""
    footer_text: str = ""
    jsonld_raw: list = field(default_factory=list)
    og_description: str = ""
    meta_description: str = ""


def _get_driver():
    # lazy singleton: starting Chrome costs ~2s, do it once per run
    global _driver
    if _driver is None:
        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        _driver = webdriver.Chrome(options=opts)
        _driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return _driver


def load(url: str):
    """Returns (Page or None, note). None means the browser failed too."""
    try:
        driver = _get_driver()
    except WebDriverException as e:
        return None, f"could not start headless Chrome: {type(e).__name__}"

    try:
        driver.get(url)
    except TimeoutException:
        # keep whatever did load; a partial DOM often already has the meta tags
        pass
    except WebDriverException as e:
        return None, f"browser load failed: {type(e).__name__}"

    # driver.get returns on document load, which for an SPA is before the JS
    # has painted anything -- poll until the body has real text in it
    deadline = time.time() + HYDRATION_WAIT
    while time.time() < deadline:
        try:
            chars = driver.execute_script("return document.body ? document.body.innerText.length : 0")
        except WebDriverException:
            chars = 0
        if chars >= HYDRATION_MIN_CHARS:
            break
        time.sleep(0.5)

    try:
        data = driver.execute_script(_HARVEST_JS)
    except WebDriverException as e:
        return None, f"DOM harvest failed: {type(e).__name__}"

    page = Page(
        url=driver.current_url or url,
        title=data.get("title", ""),
        body_text=data.get("body", ""),
        footer_text=data.get("footer", ""),
        jsonld_raw=data.get("jsonld", []) or [],
        og_description=data.get("og", ""),
        meta_description=data.get("meta", ""),
    )
    return page, ""


def shutdown():
    global _driver
    if _driver is not None:
        _driver.quit()
        _driver = None
