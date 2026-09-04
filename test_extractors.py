"""Smoke tests for the extraction rules. Run: python test_extractors.py
(no pytest dependency on purpose -- one file, plain asserts)"""

from bs4 import BeautifulSoup

from extractors import (extract_description, extract_founded_year,
                        extract_hq_country, name_matches)


def soup(html):
    return BeautifulSoup(html, "html.parser")


def test_year_from_jsonld_beats_text():
    s = soup("""<script type="application/ld+json">
                {"@type":"Organization","foundingDate":"1999-04-01"}</script>
                <p>founded in 2016</p>""")
    value, method, _ = extract_founded_year(s)
    assert value == 1999 and method == "jsonld"


def test_year_single_regex_mention():
    value, method, _ = extract_founded_year(soup("<p>We were founded in 2016 in Toronto.</p>"))
    assert value == 2016 and method == "regex"


def test_year_ambiguous_refuses():
    value, _, note = extract_founded_year(
        soup("<p>founded in 2003</p><p>established in 2005</p>"))
    assert value is None and "ambiguous" in note


def test_year_absurd_value_ignored():
    value, _, _ = extract_founded_year(soup("<p>founded in 1789</p>"))
    assert value is None


def test_country_from_jsonld():
    s = soup("""<script type="application/ld+json">
                {"@type":"Organization","address":{"addressCountry":"FR"}}</script>""")
    value, method, _ = extract_hq_country(s)
    assert value == "France" and method == "jsonld"


def test_country_footer_single():
    value, method, _ = extract_hq_country(
        soup("<footer>HQ: Paris, France. All rights reserved.</footer>"))
    assert value == "France" and method == "footer"


def test_country_footer_two_countries_refuses():
    value, _, note = extract_hq_country(
        soup("<footer>Offices in France and Germany</footer>"))
    assert value is None and "ambiguous" in note


def test_country_body_mentions_do_not_count():
    # only the footer is trusted; body copy about markets must not set HQ
    value, _, _ = extract_hq_country(soup("<p>We sell in Japan and China.</p>"))
    assert value is None


def test_description_first_sentence_of_meta():
    s = soup('<meta property="og:description" '
             'content="We build quantum computers for chemistry. Join our team today!">')
    value, method, _ = extract_description(s)
    assert value == "We build quantum computers for chemistry." and method == "og:description"


def test_description_too_short_refused():
    value, _, _ = extract_description(soup('<meta name="description" content="Welcome!">'))
    assert value is None


def test_name_match_guards_resold_domains():
    page = soup("<p>Buy this domain today! Great investment.</p>")
    assert not name_matches(page, "Exscientia plc")
    assert name_matches(soup("<p>Exscientia was a pioneer in AI drug design.</p>"),
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
