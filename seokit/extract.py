"""Pull SEO-relevant facts out of an HTML document.

One pass over the parsed tree returns a plain dict, so rules, reports and
other tools all read the same field names. Uses Python's built-in HTML parser
through BeautifulSoup, so no compiled dependency is needed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
_VIDEO_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "wistia", "player.")
NON_CONTENT = ("script", "style", "noscript", "template", "svg", "iframe", "head")


def _clean(text: Optional[str]) -> str:
    return _SPACE.sub(" ", text or "").strip()


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _flatten_jsonld(node: Any, out: list) -> None:
    """Collect every typed object, including items inside @graph and nesting."""
    if isinstance(node, list):
        for item in node:
            _flatten_jsonld(item, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _flatten_jsonld(node["@graph"], out)
        if "@type" in node:
            out.append(node)


def types_of(obj: dict) -> list[str]:
    t = obj.get("@type", [])
    return [str(x).rsplit("/", 1)[-1] for x in (t if isinstance(t, list) else [t])]


def extract(html: str, url: str = "", keep_text: bool = False) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    base = url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base = urljoin(url, base_tag["href"])
    page_host = _host(url)

    def meta(**attrs) -> list[str]:
        found = []
        for tag in soup.find_all("meta"):
            ok = all((tag.get(k) or "").lower() == v for k, v in attrs.items())
            if ok and tag.get("content") is not None:
                found.append(_clean(tag["content"]))
        return found

    titles = [_clean(t.get_text()) for t in soup.find_all("title") if not t.find_parent("svg")]
    descriptions = meta(name="description")
    robots = meta(name="robots") + meta(name="googlebot")
    canonicals = [urljoin(base, l["href"]) for l in soup.find_all("link", href=True)
                  if "canonical" in [r.lower() for r in (l.get("rel") or [])]]
    html_tag = soup.find("html")

    headings = []
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        headings.append({"level": int(h.name[1]), "text": _clean(h.get_text(" "))[:200]})

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        absolute = urljoin(base, href).split("#", 1)[0]
        rel = [r.lower() for r in (a.get("rel") or [])]
        links.append({"href": absolute, "text": _clean(a.get_text(" "))[:120],
                      "internal": _host(absolute) == page_host,
                      "nofollow": "nofollow" in rel or "ugc" in rel or "sponsored" in rel})

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        images.append({"src": urljoin(base, src) if src else "",
                       "alt": img.get("alt"),  # None means the attribute is missing
                       "width": img.get("width"), "height": img.get("height"),
                       "loading": (img.get("loading") or "").lower(),
                       "fetchpriority": (img.get("fetchpriority") or "").lower()})

    jsonld, jsonld_errors = [], []
    for i, s in enumerate(soup.find_all("script", type=re.compile(r"application/ld\+json", re.I))):
        raw = (s.string or s.get_text() or "").strip()
        if not raw:
            continue
        try:
            _flatten_jsonld(json.loads(raw), jsonld)
        except json.JSONDecodeError as exc:
            jsonld_errors.append(f"block {i + 1}: {exc.msg} at line {exc.lineno}")

    hreflang = [{"lang": (l.get("hreflang") or "").lower(), "href": urljoin(base, l["href"])}
                for l in soup.find_all("link", href=True, hreflang=True)]

    og = {t["property"][3:]: _clean(t.get("content")) for t in soup.find_all("meta", property=True)
          if t["property"].lower().startswith("og:") and t.get("content") is not None}
    twitter = {t["name"][8:]: _clean(t.get("content")) for t in soup.find_all("meta", attrs={"name": True})
               if t["name"].lower().startswith("twitter:") and t.get("content") is not None}

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src", "")
        if not src:
            source = v.find("source", src=True)
            src = source["src"] if source else ""
        videos.append({"kind": "html5", "src": urljoin(base, src) if src else "", "poster": v.get("poster")})
    for f in soup.find_all("iframe", src=True):
        if any(h in f["src"].lower() for h in _VIDEO_HOSTS):
            videos.append({"kind": "embed", "src": urljoin(base, f["src"]), "poster": None})

    phones = sorted({a["href"][4:].strip() for a in soup.find_all("a", href=True)
                     if a["href"].lower().startswith("tel:")})

    head_facts = {
        "has_viewport": bool(meta(name="viewport")),
        "author": (meta(name="author") or [""])[0],
        "published": (meta(property="article:published_time") or [""])[0],
        "modified": (meta(property="article:modified_time") or [""])[0],
    }

    # Everything below measures visible text, so non-content elements go.
    for tag in soup.find_all(NON_CONTENT):
        tag.decompose()
    body = soup.body or soup
    text = _clean(body.get_text(" "))
    words = _WORD.findall(text)

    return {
        "url": url,
        "title": titles[0] if titles else "",
        "title_count": len(titles),
        "description": descriptions[0] if descriptions else "",
        "description_count": len(descriptions),
        "robots": ", ".join(robots).lower(),
        "canonical": canonicals[0] if canonicals else "",
        "canonical_count": len(canonicals),
        "lang": (html_tag.get("lang") or "").strip() if html_tag else "",
        "headings": headings,
        "h1": [h["text"] for h in headings if h["level"] == 1],
        "links": links,
        "images": images,
        "jsonld": jsonld,
        "jsonld_types": sorted({t for obj in jsonld for t in types_of(obj)}),
        "jsonld_errors": jsonld_errors,
        "has_microdata": "itemscope" in (html or ""),
        "hreflang": hreflang,
        "og": og,
        "twitter": twitter,
        "videos": videos,
        "phones": phones,
        **head_facts,
        "word_count": len(words),
        "text_sample": text[:2000],
        **({"text": text[:60000]} if keep_text else {}),
    }
