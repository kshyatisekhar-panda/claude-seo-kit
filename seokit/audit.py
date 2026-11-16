"""Site audit: crawl, collect facts, run every rule, score.

The crawl starts at the given URL and the sitemap, stays on the same host,
skips URLs with query strings (they are the usual crawl traps) and file
downloads, respects robots.txt for its own user agent, and stops at
max_pages. Output is one JSON-ready dict.
"""

from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import net, psi as psi_mod
from . import robots as robots_mod
from . import sitemap as sitemap_mod
from .extract import extract
from .findings import AREAS, Collector, Finding, area_scores, overall_score
from .rules import PAGE_RULES, SITE_RULES
from .rules.schema import LOCAL_TYPES

_FILE = re.compile(r"\.(pdf|jpe?g|png|gif|webp|avif|svg|zip|mp4|mp3|webm|docx?|xlsx?|pptx?|css|js|json|xml|txt)$",
                   re.I)


def canonical_key(url: str) -> str:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if p.port and p.port != {"http": 80, "https": 443}.get(p.scheme):
        host = f"{host}:{p.port}"
    return urlunsplit((p.scheme, host, p.path or "/", p.query, ""))


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _crawlable(url: str, host: str) -> bool:
    p = urlsplit(url)
    return (p.scheme in ("http", "https") and (p.hostname or "").lower() == host and not p.query
            and not _FILE.search(p.path))


def _https_checks(home: net.Response, fetch: Callable) -> list[Finding]:
    found = []
    final = urlsplit(home.final_url)
    if final.scheme != "https":
        return [Finding("https-missing", "technical", "critical", "Site does not use HTTPS",
                        detail="Browsers mark it Not secure and Google prefers HTTPS pages.",
                        fix="Install a certificate (free with Let's Encrypt or your host) and redirect "
                            "all http URLs to https.")]
    if not home.header("strict-transport-security"):
        found.append(Finding("hsts-missing", "technical", "low", "No HSTS header",
                             fix="Send Strict-Transport-Security: max-age=31536000 once every page "
                                 "works over https."))
    plain = fetch(f"http://{final.netloc}/", max_redirects=0)
    if plain.status == 200:
        found.append(Finding("http-not-redirected", "technical", "high", "http version does not redirect to https",
                             detail="The same pages load on http and https, splitting signals.",
                             fix="301-redirect every http URL to its https version."))
    host = final.hostname or ""
    other = host[4:] if host.startswith("www.") else f"www.{host}"
    variant = fetch(f"https://{other}/", max_redirects=0)
    if variant.status == 200:
        found.append(Finding("host-duplicate", "technical", "medium", "Site loads on both www and non-www",
                             detail=f"https://{other}/ answers 200 instead of redirecting.",
                             fix=f"301-redirect {other} to {host}."))
    return found


def _sitemaps(origin: str, robots, fetch: Callable) -> dict:
    if robots is not None and robots.sitemaps:
        return sitemap_mod.collect(robots.sitemaps, fetch)
    for candidate in sitemap_mod.default_locations(origin):
        res = fetch(candidate)
        if res.ok and b"<" in res.body[:200]:
            return sitemap_mod.collect([candidate], fetch)
    return {"files": [], "urls": [], "truncated": False}


def audit(url: str, max_pages: int = 30, with_psi: bool = False, delay: float = 0.2,
          log: Optional[Callable[[str], None]] = None) -> dict:
    log = log or (lambda m: print(m, file=sys.stderr))
    session = net.new_session()

    def fetch(u: str, **kw) -> net.Response:
        return net.fetch(u, session=session, **kw)

    started = time.monotonic()
    home = fetch(url)
    if not home.ok:
        return {"url": url, "error": home.error or f"home page returned HTTP {home.status}"}
    origin = _origin(home.final_url)
    host = (urlsplit(origin).hostname or "").lower()

    r = fetch(urljoin(origin, "/robots.txt"))
    robots = robots_mod.parse(r.text) if r.status == 200 else None
    log("robots.txt: " + ("found" if robots else f"not found ({r.status or r.error})"))
    sm = _sitemaps(origin, robots, fetch)
    log(f"sitemap: {len(sm['urls'])} URLs in {len(sm['files'])} file(s)")
    llms = fetch(urljoin(origin, "/llms.txt"))
    has_llms = llms.status == 200 and llms.text.lstrip().startswith("#")

    collector = Collector()
    pages, status, links_to = [], {}, defaultdict(list)
    blocked_for_google = set()
    queue = [home.final_url] + [u["loc"] for u in sm["urls"][: max_pages * 2]]
    seen = set()
    responses = {canonical_key(home.final_url): home}

    while queue and len(pages) + sum(1 for s in status.values() if s != 200) < max_pages:
        target = queue.pop(0)
        key = canonical_key(target)
        if key in seen or not _crawlable(target, host):
            continue
        seen.add(key)
        if robots is not None and not robots.allowed(net.USER_AGENT, target):
            continue
        res = responses.pop(key, None) or fetch(target)
        if delay and res is not home:
            time.sleep(delay)
        status[key] = res.redirects[0][1] if res.redirects else (res.status or 0)
        for hop, code in res.redirects:
            seen.add(canonical_key(hop))
            status.setdefault(canonical_key(hop), code)
        if res.final_url:
            seen.add(canonical_key(res.final_url))
            status[canonical_key(res.final_url)] = res.status or 0
        if not res.ok or "html" not in res.header("content-type"):
            continue
        page = extract(res.text, res.final_url)
        page["status"] = res.status
        page["elapsed_ms"] = res.elapsed_ms
        pages.append(page)
        for rule in PAGE_RULES:
            rule(page, res, lambda f, _u=page["url"]: collector.add(f, _u))
        for link in page["links"]:
            if link["internal"]:
                lk = canonical_key(link["href"])
                if page["url"] not in links_to[lk]:
                    links_to[lk].append(page["url"])
                if robots is not None and not robots.allowed("Googlebot", link["href"]):
                    blocked_for_google.add(link["href"])
                if lk not in seen:
                    queue.append(link["href"])
        log(f"crawled {len(pages)}: {page['url']}")

    site = {
        "origin": origin,
        "pages": pages,
        "status": status,
        "robots": robots,
        "sitemap": sm,
        "llms_txt": has_llms,
        "blocked_links": sorted(blocked_for_google),
        "broken_links": {k: v for k, v in links_to.items() if status.get(k, 200) >= 400},
        "https_findings": _https_checks(home, fetch),
    }
    if with_psi:
        log("running PageSpeed Insights (mobile)...")
        site["psi"] = psi_mod.run(home.final_url)
    for rule in SITE_RULES:
        rule(site, lambda f, page="": collector.add(f, page))

    findings = collector.all()
    areas = [a for a in AREAS if a != "local" or site.get("local")]
    scores = area_scores(findings, len(pages), areas)
    types = {t for p in pages for t in p["jsonld_types"]}
    business = ("local" if site.get("local") else "ecommerce" if "Product" in types
                else "publisher" if types & {"Article", "BlogPosting", "NewsArticle"} else "general")
    return {
        "url": url,
        "origin": origin,
        "business_type": business,
        "pages_crawled": len(pages),
        "duration_s": round(time.monotonic() - started, 1),
        "score": overall_score(scores),
        "scores": scores,
        "counts": {s: sum(1 for f in findings if f.severity == s)
                   for s in ("critical", "high", "medium", "low", "info")},
        "findings": [f.to_dict() for f in findings],
        "ai_policy": site.get("ai_policy", []),
        "sitemap": {"files": sm["files"], "url_count": len(sm["urls"]), "truncated": sm["truncated"]},
        "psi": site.get("psi"),
        "pages": [{"url": p["url"], "status": p["status"], "title": p["title"],
                   "words": p["word_count"], "schema": p["jsonld_types"]} for p in pages],
        "local_types_seen": sorted(types & LOCAL_TYPES),
    }


def page_report(url: str, with_psi: bool = False, with_text: bool = False) -> dict:
    """Everything about one page: facts plus that page's findings."""
    res = net.fetch(url)
    if not res.ok:
        return {"url": url, "status": res.status, "error": res.error or f"HTTP {res.status}"}
    page = extract(res.text, res.final_url, keep_text=with_text)
    collector = Collector()
    for rule in PAGE_RULES:
        rule(page, res, lambda f: collector.add(f, page["url"]))
    out = {k: v for k, v in page.items() if k not in ("links", "text_sample")}
    out.update(status=res.status, elapsed_ms=res.elapsed_ms, redirects=res.redirects,
               x_robots_tag=res.header("x-robots-tag"),
               links={"internal": sum(1 for l in page["links"] if l["internal"]),
                      "external": sum(1 for l in page["links"] if not l["internal"])},
               findings=[f.to_dict() for f in collector.all()])
    if with_psi:
        out["psi"] = psi_mod.run(res.final_url)
    return out
