"""XML sitemap discovery and parsing (sitemaps.org protocol).

defusedxml refuses entity expansion and external entities, so a hostile
sitemap cannot exhaust memory or read local files.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_URLS = 50_000
MAX_BYTES = 50 * 1024 * 1024
_W3C_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?)?)?$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class Sitemap:
    url: str
    kind: str = ""  # "urlset" or "sitemapindex"
    urls: list = field(default_factory=list)  # [{"loc", "lastmod"}]
    children: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def parse(body: bytes, url: str = "") -> Sitemap:
    sm = Sitemap(url=url)
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            sm.problems.append("gzip file could not be decompressed")
            return sm
    if len(body) > MAX_BYTES:
        sm.problems.append("larger than 50 MB uncompressed (protocol limit)")
    try:
        root = SafeET.fromstring(body)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        sm.problems.append(f"not valid XML: {exc}")
        return sm
    sm.kind = _local(root.tag)
    if sm.kind not in ("urlset", "sitemapindex"):
        sm.problems.append(f"root element is <{sm.kind}>, expected <urlset> or <sitemapindex>")
        return sm
    origin_host = urlsplit(url).hostname or ""
    bad_dates = cross_host = 0
    for entry in root:
        fields = {_local(c.tag): (c.text or "").strip() for c in entry}
        loc = fields.get("loc", "")
        if not loc:
            continue
        loc = urljoin(url, loc)
        lastmod = fields.get("lastmod", "")
        if lastmod and not _W3C_DATE.match(lastmod):
            bad_dates += 1
        if origin_host and (urlsplit(loc).hostname or "") != origin_host:
            cross_host += 1
        if sm.kind == "sitemapindex":
            sm.children.append(loc)
        else:
            sm.urls.append({"loc": loc, "lastmod": lastmod})
    if len(sm.urls) > MAX_URLS:
        sm.problems.append(f"{len(sm.urls)} URLs; the limit is {MAX_URLS} per file")
    if bad_dates:
        sm.problems.append(f"{bad_dates} lastmod values are not W3C date format")
    if cross_host:
        sm.problems.append(f"{cross_host} URLs are on a different host than the sitemap")
    if sm.kind == "urlset" and not sm.urls:
        sm.problems.append("sitemap has no URLs")
    lastmods = [u["lastmod"] for u in sm.urls if u["lastmod"]]
    if len(lastmods) > 20 and len(set(lastmods)) == 1:
        sm.problems.append("every URL has the same lastmod; use each page's real change date")
    return sm


def collect(start_urls: list[str], fetch: Callable, max_files: int = 20,
            max_urls: int = 5000) -> dict:
    """Follow sitemap indexes breadth first. fetch(url) returns a net.Response."""
    queue, seen, files, urls = list(dict.fromkeys(start_urls)), set(), [], []
    while queue and len(files) < max_files and len(urls) < max_urls:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        res = fetch(url)
        if not res.ok:
            files.append({"url": url, "status": res.status, "error": res.error or f"HTTP {res.status}",
                          "kind": "", "count": 0, "problems": []})
            continue
        sm = parse(res.body, res.final_url or url)
        files.append({"url": url, "status": res.status, "error": None, "kind": sm.kind,
                      "count": len(sm.urls) or len(sm.children), "problems": sm.problems})
        queue.extend(c for c in sm.children if c not in seen)
        urls.extend(sm.urls[: max_urls - len(urls)])
    return {"files": files, "urls": urls, "truncated": bool(queue) or len(urls) >= max_urls}


def default_locations(origin: str, robots_sitemaps: Optional[list] = None) -> list[str]:
    found = list(robots_sitemaps or [])
    return found or [urljoin(origin, "/sitemap.xml"), urljoin(origin, "/sitemap_index.xml")]
