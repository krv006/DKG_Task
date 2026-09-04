"""Selenium fallback for pages that come back as a JS shell over plain HTTP.

Deliberately second in line, not first: a headless browser is ~10x slower
per page and hides HTTP status codes (no way to see a 429 or a 404 from
Selenium), so requests stays the primary transport and this only runs when
a 200 arrived with nothing useful in it.
"""

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException

PAGE_LOAD_TIMEOUT = 15  # rendering budget per page; JS-heavy sites need more than plain HTTP

_driver = None


def _get_driver():
    # lazy singleton: starting Chrome costs ~2s, most runs never need it
    global _driver
    if _driver is None:
        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        _driver = webdriver.Chrome(options=opts)
        _driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return _driver


def render(url: str):
    """Returns (html, note). html=None means rendering failed too."""
    try:
        driver = _get_driver()
    except WebDriverException as e:
        return None, f"could not start headless Chrome: {type(e).__name__}"

    try:
        driver.get(url)
    except TimeoutException:
        # keep whatever did load; partial DOM often already has the meta tags
        pass
    except WebDriverException as e:
        return None, f"render failed: {type(e).__name__}"

    html = driver.page_source or ""
    if len(html) < 200:
        return None, "rendered but page source still empty"
    return html, "rendered with headless Chrome (plain HTTP returned a JS shell)"


def shutdown():
    global _driver
    if _driver is not None:
        _driver.quit()
        _driver = None
