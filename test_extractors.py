"""Smoke tests for the extraction rules. Run: python test_extractors.py
(no pytest dependency on purpose -- one file, plain asserts; Page objects
are built by hand so no browser is needed)"""

from renderer import Page
from extractors import (extract_description, extract_founded_year,
                        extract_hq_country, name_matches)


def test_year_from_jsonld_beats_text():
    page = Page(jsonld_raw=['{"@type":"Organization","foundingDate":"1999-04-01"}'],
                body_text="founded in 2016")
    value, method, _ = extract_founded_year(page)
    assert value == 1999 and method == "jsonld"


def test_year_single_regex_mention():
    value, method, _ = extract_founded_year(Page(body_text="We were founded in 2016 in Toronto."))
    assert value == 2016 and method == "regex"


def test_year_ambiguous_refuses():
    value, _, note = extract_founded_year(
        Page(body_text="founded in 2003 ... established in 2005"))
    assert value is None and "ambiguous" in note


def test_year_absurd_value_ignored():
    value, _, _ = extract_founded_year(Page(body_text="founded in 1789"))
    assert value is None


def test_year_broken_jsonld_falls_through():
    page = Page(jsonld_raw=["{not valid json"], body_text="founded in 2016")
    value, method, _ = extract_founded_year(page)
    assert value == 2016 and method == "regex"


def test_country_from_jsonld():
    page = Page(jsonld_raw=['{"@type":"Organization","address":{"addressCountry":"FR"}}'])
    value, method, _ = extract_hq_country(page)
    assert value == "France" and method == "jsonld"


def test_country_footer_single():
    value, method, _ = extract_hq_country(
        Page(footer_text="HQ: Paris, France. All rights reserved."))
    assert value == "France" and method == "footer"


def test_country_footer_two_countries_refuses():
    value, _, note = extract_hq_country(
        Page(footer_text="Offices in France and Germany"))
    assert value is None and "ambiguous" in note


def test_country_body_mentions_do_not_count():
    # only the footer is trusted; body copy about markets must not set HQ
    value, _, _ = extract_hq_country(Page(body_text="We sell in Japan and China."))
    assert value is None


def test_description_first_sentence_of_meta():
    page = Page(og_description="We build quantum computers for chemistry. Join our team today!")
    value, method, _ = extract_description(page)
    assert value == "We build quantum computers for chemistry." and method == "og:description"


def test_description_too_short_refused():
    value, _, _ = extract_description(Page(meta_description="Welcome!"))
    assert value is None


def test_name_match_guards_resold_domains():
    assert not name_matches(Page(body_text="Buy this domain today! Great investment."),
                            "Exscientia plc")
    assert name_matches(Page(body_text="Exscientia was a pioneer in AI drug design."),
                        "Exscientia plc")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}  {e}")
    raise SystemExit(1 if fails else 0)
