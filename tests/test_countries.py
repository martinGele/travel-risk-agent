import re

import pytest

from travel_risk.countries import UnknownCountry, to_iso2, uk_slug_to_iso2, us_slug_to_iso2


def test_every_us_feed_slug_maps(us_feed_xml):
    slugs = set(re.findall(rb"destination\.([a-z0-9]+)\.html", us_feed_xml))
    assert len(slugs) > 200
    unmapped = []
    for slug in slugs:
        try:
            us_slug_to_iso2(slug.decode())
        except UnknownCountry:
            unmapped.append(slug.decode())
    assert unmapped == []


def test_every_uk_index_slug_maps(uk_index):
    children = uk_index["links"]["children"]
    assert len(children) > 200
    unmapped = []
    for child in children:
        c = child["details"]["country"]
        try:
            uk_slug_to_iso2(c["slug"], c["name"])
        except UnknownCountry:
            unmapped.append(c["slug"])
    assert unmapped == []


def test_uk_slugs_map_to_distinct_countries(uk_index):
    seen: dict[str, str] = {}
    for child in uk_index["links"]["children"]:
        c = child["details"]["country"]
        iso = uk_slug_to_iso2(c["slug"], c["name"])
        assert iso not in seen, f"{c['slug']} and {seen.get(iso)} both map to {iso}"
        seen[iso] = c["slug"]


@pytest.mark.parametrize(
    ("slug", "iso"),
    [("lbn", "LB"), ("irq", "IQ"), ("xgz", "PS"), ("xwb", "PS"), ("xks", "XK"), ("xqx", "BQ")],
)
def test_us_slug_examples(slug, iso):
    assert us_slug_to_iso2(slug) == iso


@pytest.mark.parametrize(
    ("raw", "iso"),
    [
        ("Lebanon", "LB"), ("lebanon ", "LB"), ("LB", "LB"), ("LBN", "LB"), ("Guinea", "GN"),
        ("UK", "GB"), ("United Kingdom", "GB"), ("U.S.", "US"), ("USA", "US"),
        ("UAE", "AE"), ("Türkiye", "TR"), ("Turkey", "TR"), ("Czech Republic", "CZ"),
        ("Ivory Coast", "CI"), ("South Korea", "KR"), ("Kosovo", "XK"),
    ],
)
def test_customer_country_values(raw, iso):
    assert to_iso2(raw) == iso


@pytest.mark.parametrize("raw", ["", "  ", "Narnia"])
def test_bad_customer_country_values_raise(raw):
    with pytest.raises(UnknownCountry):
        to_iso2(raw)
