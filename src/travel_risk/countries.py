"""Country code normalisation. Everything internal uses ISO 3166-1 alpha-2."""

from __future__ import annotations

from functools import cache

import pycountry

# US State Dept URL slugs (ISO alpha-3 style) that are not real ISO codes, or that we
# deliberately map differently. See docs/DECISIONS.md.
US_ALPHA3_OVERRIDES: dict[str, str] = {
    "xgz": "PS",  # Gaza
    "xwb": "PS",  # The West Bank
    "xks": "XK",  # Kosovo (user-assigned code, widely used)
    "xqx": "BQ",  # Saba and Sint Eustatius (Bonaire is "bes" -> BQ too)
}

# A few US items still use legacy URLs without an ISO slug; fall back to their FIPS Country-Tag.
# Only codes seen in the live feed are listed; anything else is skipped with a warning.
US_FIPS_FALLBACK: dict[str, str] = {
    "TN": "TO",  # Tonga (FIPS TN is ISO TO; ISO TN is Tunisia)
}
# Legacy aggregate entries already covered by per-territory items (GP, MQ, MF, BL).
US_FIPS_IGNORED: frozenset[str] = frozenset({"A3"})  # "French West Indies"

# GOV.UK foreign-travel-advice slugs whose names pycountry can't resolve by itself.
UK_SLUG_OVERRIDES: dict[str, str] = {
    "antarctica-british-antarctic-territory": "AQ",
    "bolivia": "BO",
    "bonaire-st-eustatius-saba": "BQ",
    "british-virgin-islands": "VG",
    "brunei": "BN",
    "cape-verde": "CV",
    "congo": "CG",
    "cook-islands-tokelau-and-niue": "CK",
    "cote-d-ivoire": "CI",
    "democratic-republic-of-the-congo": "CD",
    "federated-states-of-micronesia": "FM",
    "iran": "IR",
    "kosovo": "XK",
    "laos": "LA",
    "macao": "MO",
    "moldova": "MD",
    "north-korea": "KP",
    "palestine": "PS",
    "pitcairn-island": "PN",
    "russia": "RU",
    "south-korea": "KR",
    "st-helena-ascension-and-tristan-da-cunha": "SH",
    "st-kitts-and-nevis": "KN",
    "st-lucia": "LC",
    "st-maarten": "SX",
    "st-martin-and-st-barthelemy": "MF",
    "st-pierre-and-miquelon": "PM",
    "st-vincent-and-the-grenadines": "VC",
    "syria": "SY",
    "taiwan": "TW",
    "tanzania": "TZ",
    "the-gambia": "GM",
    "turkey": "TR",
    "usa": "US",
    "venezuela": "VE",
    "vietnam": "VN",
}

# Free-text country names customers type into CSVs that pycountry won't fuzzy-match well.
COMMON_NAME_OVERRIDES: dict[str, str] = {
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "usa": "US",
    "us": "US",
    "united states": "US",
    "america": "US",
    "uae": "AE",
    "russia": "RU",
    "south korea": "KR",
    "korea": "KR",
    "north korea": "KP",
    "iran": "IR",
    "syria": "SY",
    "vietnam": "VN",
    "laos": "LA",
    "turkey": "TR",
    "turkiye": "TR",
    "czech republic": "CZ",
    "ivory coast": "CI",
    "drc": "CD",
    "kosovo": "XK",
    "palestine": "PS",
    "taiwan": "TW",
    "bolivia": "BO",
    "venezuela": "VE",
    "tanzania": "TZ",
    "moldova": "MD",
    "macedonia": "MK",
}


class UnknownCountry(ValueError):
    pass


def us_slug_to_iso2(slug: str) -> str:
    """Map the alpha-3 slug from a travel.state.gov URL (e.g. 'lbn') to alpha-2."""
    slug = slug.lower().strip()
    if slug in US_ALPHA3_OVERRIDES:
        return US_ALPHA3_OVERRIDES[slug]
    country = pycountry.countries.get(alpha_3=slug.upper())
    if country is None:
        raise UnknownCountry(f"unknown US advisory slug {slug!r}")
    return country.alpha_2


def uk_slug_to_iso2(slug: str, name: str | None = None) -> str:
    """Map a GOV.UK travel-advice slug (and optional display name) to alpha-2."""
    slug = slug.lower().strip()
    if slug in UK_SLUG_OVERRIDES:
        return UK_SLUG_OVERRIDES[slug]
    for candidate in (name, slug.replace("-", " ")):
        if candidate:
            try:
                return _lookup_name(candidate)
            except UnknownCountry:
                continue
    raise UnknownCountry(f"unknown UK travel-advice slug {slug!r}")


def to_iso2(value: str) -> str:
    """Normalise anything a customer might put in a 'country' column to alpha-2."""
    raw = value.strip()
    if not raw:
        raise UnknownCountry("empty country")
    key = raw.lower().replace(".", "")
    if key in COMMON_NAME_OVERRIDES:
        return COMMON_NAME_OVERRIDES[key]
    if len(raw) == 2 and raw.isalpha() and (
        raw.upper() == "XK" or pycountry.countries.get(alpha_2=raw.upper())
    ):
        return raw.upper()
    if len(raw) == 3 and raw.isalpha():
        country = pycountry.countries.get(alpha_3=raw.upper())
        if country:
            return country.alpha_2
    return _lookup_name(raw)


@cache
def _lookup_name(name: str) -> str:
    try:
        return pycountry.countries.lookup(name).alpha_2
    except LookupError:
        pass
    try:
        matches = pycountry.countries.search_fuzzy(name)
    except LookupError as exc:
        raise UnknownCountry(f"unknown country {name!r}") from exc
    if len(matches) != 1:
        raise UnknownCountry(f"ambiguous country {name!r}: {[m.alpha_2 for m in matches[:5]]}")
    return matches[0].alpha_2
