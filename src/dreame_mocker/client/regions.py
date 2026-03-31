"""Region resolution logic for the Dreame cloud API.

Dreame accounts have an associated country that determines which regional
API endpoint hosts their device data.  Auth can happen on any region, but
device commands must go to the correct one.
"""

from __future__ import annotations

# Country code -> region prefix.  Countries not listed here default to "eu".
COUNTRY_TO_REGION: dict[str, str] = {
    "CN": "cn",
    "US": "us",
    "CA": "us",
    # Everything else (GB, DE, FR, ...) defaults to "eu" via fallback.
}

DEFAULT_PORT = 13267


def region_from_host(host: str) -> str:
    """Extract the region prefix from a Dreame host.

    ``"eu.iot.dreame.tech"`` -> ``"eu"``
    ``"localhost"`` -> ``"eu"`` (fallback)
    """
    first = host.split(".")[0]
    if first in ("eu", "us", "cn"):
        return first
    return "eu"


def region_for_country(country: str, fallback: str = "eu") -> str:
    """Map an account country code to an API region prefix."""
    return COUNTRY_TO_REGION.get(country.upper(), fallback)


def base_url(region: str, port: int = DEFAULT_PORT) -> str:
    """Build ``https://{region}.iot.dreame.tech:{port}``."""
    return f"https://{region}.iot.dreame.tech:{port}"
