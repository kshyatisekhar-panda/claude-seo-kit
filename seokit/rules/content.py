"""Content rules: titles, descriptions, headings, depth, images and trust signals (E-E-A-T)."""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from ..findings import Finding

THIN_WORDS = 200
TRUST_PAGES = {
    "about": re.compile(r"/(about|om-oss|om|about-us|uber-uns|qui-sommes-nous)(/|$)", re.I),
    "contact": re.compile(r"/(contact|kontakt|contact-us|kontakta-oss)(/|$)", re.I),
    "privacy": re.compile(r"/(privacy|integritet|privacy-policy|integritetspolicy|datenschutz)", re.I),
}
_UTILITY = re.compile(r"/(contact|kontakt|login|cart|checkout|search|sok|tack|thank|privacy|terms|"
                      r"cookies?|404)(/|$)", re.I)


def _is_article(page: dict) -> bool:
    return bool({"Article", "BlogPosting", "NewsArticle"} & set(page["jsonld_types"])) or any(
        s in page["url"] for s in ("/blog/", "/news/", "/articles/", "/guide"))


def page_rules(page: dict, res, add) -> None:
    title, desc = page["title"], page["description"]
    if title and len(title) > 65:
        add(Finding("title-long", "content", "low", "Title likely cut off in results",
                    detail=f"{len(title)} characters; Google shows roughly 50 to 60.",
                    fix="Put the main topic first and trim to about 60 characters."))
    elif title and len(title) < 15:
        add(Finding("title-short", "content", "low", "Very short title",
                    detail=f"'{title}' says little about the page.",
                    fix="Describe the page's topic and add the brand at the end."))
    if not desc:
        add(Finding("description-missing", "content", "medium", "No meta description",
                    detail="Google writes its own snippet, often from the wrong part of the page.",
                    fix="Write 120 to 155 characters saying what the reader gets."))
    elif len(desc) > 170:
        add(Finding("description-long", "content", "low", "Meta description will be cut off",
                    detail=f"{len(desc)} characters.", fix="Keep it under about 155 characters."))

    h1 = page["h1"]
    if not h1:
        add(Finding("h1-missing", "content", "medium", "No H1 heading",
                    fix="Give the page one H1 that states its topic."))
    elif len(h1) > 1:
        add(Finding("h1-multiple", "content", "low", "Several H1 headings",
                    detail=f"{len(h1)} H1s.", fix="Keep one H1; make the others H2."))
    levels = [h["level"] for h in page["headings"]]
    if any(b - a > 1 for a, b in zip(levels, levels[1:])):
        add(Finding("heading-skip", "content", "low", "Heading levels skip",
                    detail="For example an H2 followed directly by an H4.",
                    fix="Step down one level at a time; style with CSS, not heading level."))

    path = urlsplit(page["url"]).path
    if path not in ("", "/") and not _UTILITY.search(path) and page["word_count"] < THIN_WORDS:
        add(Finding("thin-content", "content", "medium", "Thin page",
                    detail=f"{page['word_count']} words of visible text.",
                    fix="Answer the visitor's question fully, or merge the page with a stronger one "
                        "and redirect it."))

    missing_alt = [i for i in page["images"] if i["alt"] is None and i["src"]]
    if missing_alt:
        add(Finding("img-alt-missing", "content", "medium", "Images without alt text",
                    detail=f"{len(missing_alt)} image(s) have no alt attribute.",
                    fix='Describe each meaningful image; use alt="" for decorative ones.'))
    long_alt = [i for i in page["images"] if i["alt"] and len(i["alt"]) > 150]
    if long_alt:
        add(Finding("img-alt-long", "content", "low", "Very long alt text",
                    fix="Keep alt text to a short description; it is not a place for keywords."))

    if _is_article(page):
        byline = page["author"] or any(
            isinstance(o.get("author"), (dict, list, str)) and o.get("author") for o in page["jsonld"])
        if not byline:
            add(Finding("author-missing", "content", "medium", "Articles do not name an author",
                        detail="Readers and search engines look for who wrote it and why they know.",
                        fix="Show the author with a link to a bio page, and add author to the "
                            "Article markup."))
        dated = page["published"] or page["modified"] or any(
            o.get("datePublished") or o.get("dateModified") for o in page["jsonld"])
        if not dated:
            add(Finding("date-missing", "content", "low", "Articles have no publish or update date",
                        fix="Show the publish date and the last real update, and add them to the markup."))

    if not page["og"].get("title") or not page["og"].get("image"):
        add(Finding("og-missing", "content", "low", "Incomplete Open Graph tags",
                    detail="Shared links on social and chat apps show no proper title or image.",
                    fix="Add og:title, og:description and og:image (1200 x 630)."))


def site_rules(site: dict, add) -> None:
    pages = site["pages"]
    if not pages:
        return
    links = {l["href"] for p in pages for l in p["links"] if l["internal"]} | {p["url"] for p in pages}
    for name, rx in TRUST_PAGES.items():
        if not any(rx.search(urlsplit(u).path) for u in links):
            severity = "low" if name == "privacy" else "medium"
            add(Finding(f"trust-{name}-missing", "content", severity, f"No {name} page found",
                        detail=f"No link to {'an' if name == 'about' else 'a'} {name} page was found on the crawled pages.",
                        fix={"about": "Add an About page: who runs the site, their experience, and why "
                                      "they can be trusted.",
                             "contact": "Add a Contact page with real ways to reach you.",
                             "privacy": "Add a privacy policy, required in most countries if you "
                                        "collect any data."}[name]))
    descs = defaultdict(list)
    for p in pages:
        if p["status"] == 200 and p["description"] and "noindex" not in p["robots"]:
            descs[p["description"].strip().lower()].append(p["url"])
    for urls in descs.values():
        if len(urls) > 1:
            for u in urls:
                add(Finding("description-duplicate", "content", "low", "Duplicate meta descriptions",
                            detail=f"{len(urls)} pages share one description.",
                            fix="Write a description per page from its own content."), page=u)
