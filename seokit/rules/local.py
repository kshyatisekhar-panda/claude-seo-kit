"""Local SEO rules, run only when the site looks like a local business."""

from __future__ import annotations

import re

from ..extract import types_of
from ..findings import Finding
from .schema import LOCAL_TYPES

_MAPS = re.compile(r"(google\.[a-z.]+/maps|maps\.google\.|goo\.gl/maps|maps\.app\.goo\.gl|g\.page/)", re.I)


def _digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone)
    return d[-9:]  # compare national part; ignores +46 vs 0 prefixes


def is_local(pages: list[dict]) -> bool:
    if any(set(p["jsonld_types"]) & LOCAL_TYPES for p in pages):
        return True
    has_phone = any(p["phones"] for p in pages)
    has_map = any(_MAPS.search(l["href"]) for p in pages for l in p["links"])
    return has_phone and has_map


def site_rules(site: dict, add) -> None:
    pages = site["pages"]
    if not pages or not is_local(pages):
        return
    site["local"] = True
    businesses = [o for p in pages for o in p["jsonld"] if set(types_of(o)) & LOCAL_TYPES]
    if not businesses:
        add(Finding("local-schema-missing", "local", "high", "No LocalBusiness markup",
                    detail="The site looks like a local business but does not say so in structured data.",
                    fix="Add the most specific LocalBusiness type (for example CafeOrCoffeeShop or Dentist) "
                        "with name, address, telephone, geo, openingHoursSpecification and url.",
                    ), page=pages[0]["url"])
    else:
        b = businesses[0]
        address = b.get("address") if isinstance(b.get("address"), dict) else {}
        missing = [k for k in ("streetAddress", "addressLocality", "postalCode", "addressCountry")
                   if not address.get(k)]
        if missing:
            add(Finding("local-address-incomplete", "local", "medium", "Business address is incomplete",
                        detail=f"PostalAddress lacks {', '.join(missing)}.",
                        fix="Use the exact address shown on your Google Business Profile."))
        for key, label, sev in (("telephone", "phone number", "medium"),
                                ("openingHoursSpecification", "opening hours", "medium"),
                                ("geo", "coordinates (geo)", "low")):
            if not b.get(key) and not (key == "openingHoursSpecification" and b.get("openingHours")):
                add(Finding(f"local-{key.lower()}-missing", "local", sev, f"Business markup has no {label}",
                            fix=f"Add {key} with the same value as on your Google Business Profile."))
        if b.get("sameAs") in (None, "", []):
            add(Finding("local-sameas-missing", "local", "low", "Business markup links to no profiles",
                        fix="Add sameAs with your Google Business Profile, Facebook and Instagram URLs."))

    phones = {_digits(n) for p in pages for n in p["phones"] if len(_digits(n)) >= 7}
    if len(phones) > 1:
        add(Finding("local-nap-phone", "local", "medium", "Different phone numbers across pages",
                    detail=f"{len(phones)} different numbers in tel: links.",
                    fix="Use one main number everywhere, matching your Google Business Profile, unless "
                        "each location page shows its own."))
    if not any(p["phones"] for p in pages):
        add(Finding("local-no-tel-link", "local", "low", "No tap-to-call phone link",
                    fix='Link the phone number with href="tel:+46..." so mobile visitors can call.'))
    if not any(_MAPS.search(l["href"]) for p in pages for l in p["links"]):
        add(Finding("local-no-maps-link", "local", "low", "No link to directions",
                    fix="Link to your Google Maps listing from the contact page and footer."))
