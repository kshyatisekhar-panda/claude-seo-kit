"""AI search rules: crawler access, content that AI systems can read, and quotable structure."""

from __future__ import annotations

from urllib.parse import urlsplit

from ..findings import Finding
from ..robots import ai_policy


def page_rules(page: dict, res, add) -> None:
    path = urlsplit(page["url"]).path
    scripts = res.text.count("<script") if res.text else 0
    if page["word_count"] < 60 and scripts >= 3 and path in ("", "/"):
        add(Finding("ai-js-only-content", "ai", "high", "Content appears only after JavaScript runs",
                    detail=f"The HTML has {page['word_count']} words of text and {scripts} scripts. "
                           "Google renders JavaScript, but many AI crawlers read only the raw HTML.",
                    fix="Render the main content on the server (SSR or static generation)."))


def site_rules(site: dict, add) -> None:
    robots = site.get("robots")
    if robots is not None:
        policy = ai_policy(robots)
        site["ai_policy"] = policy
        search = [p for p in policy if p["purpose"] in ("search", "user")]
        blocked = [p["agent"] for p in search if not p["allowed"]]
        if blocked and len(blocked) == len(search):
            add(Finding("ai-search-blocked", "ai", "high", "AI search assistants are blocked",
                        detail=f"robots.txt blocks {', '.join(blocked)}. These fetch pages to answer "
                               "questions with a link back, so blocking them removes the site from "
                               "those answers.",
                        fix="Allow the search and user agents; block only the training crawlers if "
                            "that is the goal."))
        elif blocked:
            add(Finding("ai-search-partly-blocked", "ai", "medium", "Some AI search assistants are blocked",
                        detail=f"Blocked: {', '.join(blocked)}.",
                        fix="Check this matches your intent; these crawlers send visitors, not "
                            "training data."))
        training_blocked = [p["agent"] for p in policy if p["purpose"] == "training" and not p["allowed"]]
        add(Finding("ai-policy", "ai", "info", "AI crawler policy",
                    detail=(f"Training crawlers blocked: {', '.join(training_blocked)}."
                            if training_blocked else "No AI crawler is blocked.") +
                           " Decide per purpose: training, search and user fetches."))
    if site.get("llms_txt") is False:
        add(Finding("llms-txt-missing", "ai", "info", "No llms.txt",
                    detail="llms.txt is an optional proposal for giving AI tools a curated map of the "
                           "site. Google does not use it, so it is low priority.",
                    fix="Add /llms.txt with a title, one-line summary and links to key pages if you "
                        "want to support tools that read it."))
    pages = site["pages"]
    if pages:
        home = pages[0]
        if not home["description"] and home["word_count"] < 150:
            add(Finding("ai-no-summary", "ai", "medium", "Home page does not say what the site is",
                        detail="Little text and no description on the home page, so AI systems have "
                               "nothing clear to quote about you.",
                        fix="Add a short, plain statement near the top: who you are, what you offer, "
                            "where."), page=home["url"])
        content = [p for p in pages if p["word_count"] >= 600]
        unstructured = [p for p in content if sum(1 for h in p["headings"] if h["level"] in (2, 3)) < 2]
        for p in unstructured[:15]:
            add(Finding("ai-wall-of-text", "ai", "low", "Long pages without section headings",
                        detail="Answers are easier to find and quote when each section has a clear "
                               "heading.",
                        fix="Break long pages into question-shaped H2 sections with a direct answer "
                            "first."), page=p["url"])
