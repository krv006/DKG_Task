import time
from dataclasses import dataclass, field

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException

PAGE_LOAD_TIMEOUT = 15
HYDRATION_WAIT = 8
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
    try:
        driver = _get_driver()
    except WebDriverException as e:
        return None, f"could not start headless Chrome: {type(e).__name__}"

    try:
        driver.get(url)
    except TimeoutException:
        pass
    except WebDriverException as e:
        return None, f"browser load failed: {type(e).__name__}"

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
