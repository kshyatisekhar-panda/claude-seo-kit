"""Technical rules: status, indexability, canonicals, hreflang, HTTPS, robots and sitemaps."""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from ..findings import Finding

_HREFLANG = re.compile(r"^(x-default|[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|\d{3}))?)$")


def _norm(url: str) -> str:
    p = urlsplit(url)
    return f"{(p.hostname or '').lower()}{p.path.rstrip('/') or '/'}"


def page_rules(page: dict, res, add) -> None:
    url = page["url"]
    if res.redirects and len(res.redirects) > 1:
        add(Finding("redirect-chain", "technical", "medium", "Redirect chain",
                    detail=f"{len(res.redirects)} hops before the page loads.",
                    fix="Point links and redirects straight at the final URL."))
    if res.redirects and any(code in (302, 307) for _, code in res.redirects):
        add(Finding("redirect-temporary", "technical", "low", "Temporary redirect used",
                    detail="302 or 307 tells search engines the move is temporary.",
                    fix="Use 301 or 308 for permanent moves."))

    robots = page["robots"] + ", " + res.header("x-robots-tag").lower()
    if "noindex" in robots:
        add(Finding("noindex", "technical", "high", "Page is excluded from search (noindex)",
                    detail="A robots meta tag or X-Robots-Tag header says noindex.",
                    fix="Remove noindex if the page should rank. Keep it on thank-you, search-result "
                        "and draft pages."))
    if page["title_count"] == 0 or not page["title"]:
        add(Finding("title-missing", "technical", "critical", "Missing title tag",
                    fix="Give every page a unique <title> describing its main topic."))
    elif page["title_count"] > 1:
        add(Finding("title-multiple", "technical", "medium", "More than one title tag",
                    fix="Render a single <title>; check the layout and page both add one."))

    canonical = page["canonical"]
    if page["canonical_count"] > 1:
        add(Finding("canonical-multiple", "technical", "high", "Conflicting canonical tags",
                    detail="With several canonicals Google may ignore them all.",
                    fix="Keep exactly one rel=canonical per page."))
    if not canonical:
        add(Finding("canonical-missing", "technical", "medium", "No canonical tag",
                    fix="Add an absolute self-referencing rel=canonical."))
    elif urlsplit(canonical).hostname and urlsplit(canonical).hostname != urlsplit(url).hostname:
        add(Finding("canonical-cross-host", "technical", "high", "Canonical points to another host",
                    detail=f"Canonical is {canonical}.",
                    fix="Point the canonical at this site's own URL unless the content truly lives there."))
    elif _norm(canonical) != _norm(url):
        add(Finding("canonical-other", "technical", "info", "Page canonicalises to another URL",
                    detail=f"Canonical is {canonical}; this URL will usually not be indexed.",
                    fix="Fine for duplicates; make sure internal links use the canonical URL."))

    if not page["has_viewport"]:
        add(Finding("viewport-missing", "technical", "high", "No mobile viewport",
                    detail="Google indexes the mobile version; without a viewport the page renders "
                           "zoomed out on phones.",
                    fix='Add <meta name="viewport" content="width=device-width, initial-scale=1">.'))
    if not page["lang"]:
        add(Finding("lang-missing", "technical", "low", "No language declared",
                    fix='Set <html lang="en"> (or the page language).'))

    if url.startswith("https://"):
        insecure = [i["src"] for i in page["images"] if i["src"].startswith("http://")]
        if insecure:
            add(Finding("mixed-content", "technical", "medium", "Insecure images on an HTTPS page",
                        detail=f"{len(insecure)} image(s) load over http, e.g. {insecure[0][:80]}.",
                        fix="Serve every resource over https."))
    if res.elapsed_ms > 2000:
        add(Finding("slow-response", "technical", "medium", "Slow server response",
                    detail=f"The HTML took {res.elapsed_ms} ms to download.",
                    fix="Cache rendered pages, use a CDN, and check slow database or API calls."))
    if len(res.body) > 1_500_000:
        add(Finding("html-heavy", "technical", "low", "Very large HTML",
                    detail=f"{len(res.body) // 1024} KB of HTML.",
                    fix="Trim inlined data and markup; large documents slow down every crawl."))

    langs = [h["lang"] for h in page["hreflang"]]
    if langs:
        bad = [l for l in langs if not _HREFLANG.match(l)]
        if bad:
            add(Finding("hreflang-invalid", "technical", "high", "Invalid hreflang codes",
                        detail=f"Not ISO 639-1 / 3166-1 codes: {', '.join(bad[:5])}.",
                        fix='Use codes like "en", "sv", "en-gb", "es-419" or "x-default".'))
        self_ref = canonical or url
        if not any(_norm(h["href"]) == _norm(self_ref) for h in page["hreflang"]):
            add(Finding("hreflang-no-self", "technical", "medium", "hreflang set leaves out the page itself",
                        fix="Each language version lists every version, itself included."))
        if "x-default" not in langs:
            add(Finding("hreflang-no-default", "technical", "low", "No x-default hreflang",
                        fix="Add x-default pointing to the language picker or main version."))

    internal_nofollow = [l["href"] for l in page["links"] if l["internal"] and l["nofollow"]]
    if internal_nofollow:
        add(Finding("internal-nofollow", "technical", "low", "Internal links marked nofollow",
                    detail=f"{len(internal_nofollow)} internal link(s) carry rel=nofollow.",
                    fix="Remove nofollow from links to your own pages."))


def site_rules(site: dict, add) -> None:
    for f in site.get("https_findings", []):
        add(f)

    robots = site.get("robots")
    if robots is None:
        add(Finding("robots-missing", "technical", "low", "No robots.txt",
                    detail="Without it crawlers assume everything is allowed, which is fine, but you "
                           "cannot point them at your sitemap.",
                    fix="Add /robots.txt with at least a Sitemap: line."))
    else:
        if not robots.allowed("Googlebot", "/"):
            add(Finding("robots-blocks-site", "technical", "critical", "robots.txt blocks Googlebot from the site",
                        fix="Remove the Disallow: / rule that applies to Googlebot or *."))
        for err in robots.errors[:3]:
            add(Finding("robots-syntax", "technical", "low", "robots.txt has lines crawlers ignore",
                        detail=err, fix="Fix or remove the line."))
        for u in site.get("blocked_links", [])[:50]:
            add(Finding("robots-blocks-page", "technical", "high", "Linked pages blocked by robots.txt",
                        detail="Blocked pages cannot be crawled; if linked they can still appear "
                               "without a description.",
                        fix="Unblock pages that should rank, or stop linking to them."), page=u)

    sm = site.get("sitemap") or {}
    if not sm.get("urls") and not any(f.get("kind") for f in sm.get("files", [])):
        add(Finding("sitemap-missing", "technical", "medium", "No XML sitemap found",
                    detail="Checked robots.txt Sitemap lines and /sitemap.xml.",
                    fix="Generate a sitemap of all canonical, indexable pages and list it in robots.txt."))
    else:
        if robots is not None and not robots.sitemaps:
            add(Finding("sitemap-not-in-robots", "technical", "low", "Sitemap not listed in robots.txt",
                        fix="Add 'Sitemap: https://your-site/sitemap.xml' to robots.txt."))
        for f in sm.get("files", []):
            for problem in f.get("problems", []):
                add(Finding("sitemap-problem", "technical", "medium", "Sitemap format problem",
                            detail=f"{f['url']}: {problem}", fix="Regenerate the sitemap from your page list."))
            if f.get("error"):
                add(Finding("sitemap-unreachable", "technical", "high", "Sitemap cannot be fetched",
                            detail=f"{f['url']}: {f['error']}", fix="Make the sitemap URL return 200."))
        from ..audit import canonical_key

        by_url = {canonical_key(p["url"]): p for p in site["pages"]}
        status = site.get("status", {})
        for entry in sm.get("urls", []):
            key = canonical_key(entry["loc"])
            code = status.get(key)
            if code is not None and code != 200:
                add(Finding("sitemap-non-200", "technical", "medium", "Sitemap lists URLs that do not return 200",
                            detail="Includes redirects, which belong out of the sitemap too.",
                            fix="List only final, working URLs."), page=entry["loc"])
                continue
            p = by_url.get(key)
            if p is None:
                continue
            if "noindex" in p["robots"]:
                add(Finding("sitemap-noindex", "technical", "medium", "Sitemap lists noindex pages",
                            fix="Remove noindex pages from the sitemap."), page=entry["loc"])
            elif p["canonical"] and _norm(p["canonical"]) != _norm(entry["loc"]):
                add(Finding("sitemap-non-canonical", "technical", "low", "Sitemap lists non-canonical URLs",
                            fix="List each page's canonical URL only."), page=entry["loc"])

    for target, sources in site.get("broken_links", {}).items():
        add(Finding("broken-internal-link", "technical", "high", "Internal links to broken pages",
                    detail=f"{target} is linked from {len(sources)} page(s), e.g. {sources[0]}.",
                    fix="Update the links or redirect the broken URL to its replacement."), page=target)

    titles = defaultdict(list)
    for p in site["pages"]:
        if p["status"] == 200 and p["title"] and "noindex" not in p["robots"]:
            titles[p["title"].strip().lower()].append(p["url"])
    for urls in titles.values():
        if len(urls) > 1:
            for u in urls:
                add(Finding("title-duplicate", "technical", "medium", "Duplicate titles",
                            detail=f"{len(urls)} pages share the title of {urls[0]}.",
                            fix="Write a unique title per page, built from its own heading or topic."), page=u)
