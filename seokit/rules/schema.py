"""Structured data rules: JSON-LD validity and Google rich result requirements.

REQUIREMENTS lists, per type, the properties Google documents as required for
the rich result and the ones it recommends. Sources: Google Search Central
structured data guides. Types that have no rich result are still useful for
understanding, so they are checked only for basic sanity.
"""

from __future__ import annotations

from ..extract import types_of
from ..findings import Finding

LOCAL_TYPES = {
    "LocalBusiness", "Restaurant", "CafeOrCoffeeShop", "Bakery", "BarOrPub", "FoodEstablishment",
    "Store", "ClothingStore", "Dentist", "MedicalClinic", "Physician", "HealthAndBeautyBusiness",
    "BeautySalon", "HairSalon", "AutoRepair", "Hotel", "LodgingBusiness", "ProfessionalService",
    "LegalService", "Attorney", "RealEstateAgent", "HomeAndConstructionBusiness", "Plumber",
    "Electrician", "SportsActivityLocation", "ExerciseGym", "AutomotiveBusiness", "FinancialService",
}

REQUIREMENTS = {
    "Article": ([], ["headline", "image", "datePublished", "dateModified", "author"]),
    "NewsArticle": ([], ["headline", "image", "datePublished", "dateModified", "author"]),
    "BlogPosting": ([], ["headline", "image", "datePublished", "dateModified", "author"]),
    "Product": (["name"], ["image", "description", "offers", "brand", "sku"]),
    "Offer": (["price", "priceCurrency"], ["availability", "url"]),
    "LocalBusiness": (["name", "address"], ["telephone", "url", "openingHoursSpecification", "geo",
                                            "image", "priceRange"]),
    "Organization": ([], ["name", "url", "logo", "sameAs"]),
    "WebSite": (["name", "url"], []),
    "BreadcrumbList": (["itemListElement"], []),
    "Event": (["name", "startDate", "location"], ["endDate", "eventStatus", "image", "offers",
                                                  "description", "organizer"]),
    "Recipe": (["name", "image"], ["author", "datePublished", "description", "recipeIngredient",
                                   "recipeInstructions", "totalTime", "nutrition"]),
    "VideoObject": (["name", "thumbnailUrl", "uploadDate"], ["description", "duration",
                                                             "contentUrl", "embedUrl"]),
    "JobPosting": (["title", "description", "datePosted", "hiringOrganization"],
                   ["validThrough", "employmentType", "baseSalary", "jobLocation"]),
    "Review": (["itemReviewed", "reviewRating", "author"], []),
    "AggregateRating": (["ratingValue"], ["ratingCount", "reviewCount", "bestRating"]),
    "SoftwareApplication": (["name"], ["offers", "aggregateRating", "operatingSystem",
                                       "applicationCategory"]),
    "Course": (["name", "description"], ["provider"]),
}
RETIRED = {
    "HowTo": "Google stopped showing HowTo rich results in September 2023. The markup does no harm "
             "but earns no rich result; remove it only if it is costly to maintain.",
    "SpecialAnnouncement": "Google no longer shows rich results for SpecialAnnouncement.",
}
LIMITED = {
    "FAQPage": "Google shows FAQ rich results only for a narrow set of authoritative sites, so do "
               "not expect a search feature from it. Keep it only if the Q&A is visible on the page.",
}


def _rule_key(t: str) -> str:
    return "LocalBusiness" if t in LOCAL_TYPES else t


def _missing(obj: dict, props: list[str]) -> list[str]:
    out = []
    for p in props:
        v = obj.get(p)
        if v in (None, "", [], {}):
            out.append(p)
    return out


def check_object(obj: dict) -> list[tuple[str, str, str]]:
    """Return (severity, id_suffix, message) problems for one typed object."""
    problems = []
    for t in types_of(obj):
        key = _rule_key(t)
        if key in RETIRED:
            problems.append(("info", f"retired-{key.lower()}", RETIRED[key]))
        if key in LIMITED:
            problems.append(("info", f"limited-{key.lower()}", LIMITED[key]))
        req, rec = REQUIREMENTS.get(key, ([], []))
        miss_req, miss_rec = _missing(obj, req), _missing(obj, rec)
        if miss_req:
            problems.append(("high", f"{key.lower()}-required",
                             f"{t} is missing required: {', '.join(miss_req)}"))
        if miss_rec:
            problems.append(("low", f"{key.lower()}-recommended",
                             f"{t} could add: {', '.join(miss_rec)}"))
        if key == "Product" and not any(obj.get(p) for p in ("offers", "review", "aggregateRating")):
            problems.append(("high", "product-snippet",
                             "Product needs offers, review or aggregateRating to be eligible for "
                             "product rich results"))
        if key == "BreadcrumbList":
            for i, item in enumerate(obj.get("itemListElement") or []):
                if isinstance(item, dict) and (item.get("position") is None or not
                                               (item.get("name") or isinstance(item.get("item"), dict))):
                    problems.append(("medium", "breadcrumb-item",
                                     f"breadcrumb item {i + 1} needs position and name"))
                    break
    offers = obj.get("offers")
    for offer in offers if isinstance(offers, list) else [offers]:
        if isinstance(offer, dict) and "Offer" in types_of(offer) and _missing(offer, ["price", "priceCurrency"]):
            problems.append(("medium", "offer-price", "an Offer is missing price or priceCurrency"))
            break
    return problems


def _title(suffix: str, message: str) -> str:
    fixed = {"product-snippet": "Product markup cannot earn product rich results",
             "breadcrumb-item": "Breadcrumb markup has incomplete items",
             "offer-price": "Offer markup is missing price details"}
    if suffix in fixed:
        return fixed[suffix]
    head, _, kind = suffix.rpartition("-")
    typ = message.split(" ", 1)[0]
    if head == "retired":
        return f"{ {k.lower(): k for k in RETIRED}.get(kind, kind)} rich results are retired"
    if head == "limited":
        return "FAQ rich results are limited" if kind == "faqpage" else f"{typ} rich results are limited"
    return {"required": f"{typ} markup is missing required properties",
            "recommended": f"{typ} markup could be more complete"}.get(kind, message.split(".")[0][:80])


def page_rules(page: dict, res, add) -> None:
    for err in page["jsonld_errors"]:
        add(Finding("schema-json-invalid", "schema", "critical", "Structured data does not parse",
                    detail=f"JSON-LD has a syntax error ({err}). Search engines ignore the whole block.",
                    fix="Fix the JSON syntax; generate it with JSON.stringify or a schema helper instead of "
                        "writing it by hand."))
    for obj in page["jsonld"]:
        ctx = str(obj.get("@context", "")) if isinstance(obj, dict) else ""
        if ctx and "schema.org" not in ctx:
            add(Finding("schema-context", "schema", "medium", "Structured data uses an unexpected @context",
                        detail=f"@context is '{ctx[:60]}'.", fix='Use "@context": "https://schema.org".'))
        for severity, suffix, message in check_object(obj):
            add(Finding(f"schema-{suffix}", "schema", severity, _title(suffix, message), detail=message,
                        fix="Add the properties with real values from the page; never invent ratings, "
                            "prices or reviews."))
        types = set(types_of(obj))
        if types & LOCAL_TYPES and (obj.get("aggregateRating") or obj.get("review")):
            add(Finding("schema-self-serving-reviews", "schema", "medium",
                        "Reviews on your own business markup",
                        detail="Google does not show review stars for reviews a LocalBusiness or "
                               "Organization publishes about itself.",
                        fix="Keep real reviews visible on the page, but do not expect stars from them."))


def site_rules(site: dict, add) -> None:
    pages = site["pages"]
    if not pages:
        return
    all_types = {t for p in pages for t in p["jsonld_types"]}
    if not all_types and not any(p["has_microdata"] for p in pages):
        add(Finding("schema-none", "schema", "high", "No structured data on any page",
                    detail="Structured data helps search engines and AI systems understand what the "
                           "site is and can earn rich results.",
                    fix="Start with Organization and WebSite on the home page, then the type that fits "
                        "the content: Article, Product, LocalBusiness, Event or Recipe."))
        return
    home = pages[0]
    if not {"Organization", "WebSite"} & set(home["jsonld_types"]) and not set(home["jsonld_types"]) & LOCAL_TYPES:
        add(Finding("schema-no-entity", "schema", "low", "Home page does not describe the site's owner",
                    detail="No Organization, WebSite or LocalBusiness markup on the home page.",
                    fix="Add Organization (name, url, logo, sameAs profiles) and WebSite (name, url)."),
            page=home["url"])
    article_like = [p for p in pages[1:] if any(s in p["url"] for s in ("/blog/", "/news/", "/article"))]
    unmarked = [p for p in article_like if not {"Article", "BlogPosting", "NewsArticle"} & set(p["jsonld_types"])]
    if article_like and len(unmarked) / len(article_like) > 0.5:
        for p in unmarked[:20]:
            add(Finding("schema-article-missing", "schema", "medium", "Articles have no Article markup",
                        detail="Article markup tells search engines the headline, author and dates.",
                        fix="Add Article or BlogPosting with headline, author, datePublished, "
                            "dateModified and image."), page=p["url"])
