"""extract.py, robots.py and sitemap.py."""

from __future__ import annotations

import gzip

from seokit import robots, sitemap
from seokit.extract import extract

HTML = """<!doctype html><html lang="sv"><head>
<title>Fika i Stockholm</title><title>second</title>
<meta name="description" content="  Guide   to fika. ">
<meta name="robots" content="max-image-preview:large">
<meta name="viewport" content="width=device-width">
<meta name="author" content="Kshyati">
<meta property="og:title" content="Fika"><meta name="twitter:card" content="summary">
<link rel="canonical" href="/fika/">
<link rel="alternate" hreflang="en" href="https://ex.com/en/fika/">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
  {"@type":"Organization","name":"X"},{"@type":["CafeOrCoffeeShop"],"name":"Y"}]}</script>
<script type="application/ld+json">{bad json}</script>
</head><body>
<h1>Fika</h1><h3>Skipped level</h3>
<p>Kanelbullar och kaffe är en del av vardagen. Det här är en guide.</p>
<a href="/om-oss">Om oss</a><a href="https://other.com/x" rel="nofollow">Ext</a>
<a href="tel:+46 8 123 45">Ring</a><a href="#top">top</a>
<img src="a.jpg"><img src="b.jpg" alt="" loading="lazy" width="10" height="10">
<iframe src="https://www.youtube.com/embed/abc"></iframe>
<video><source src="/v.mp4"></video>
<script>var hidden = "not text";</script>
</body></html>"""


def test_extract_fields():
    d = extract(HTML, "https://ex.com/fika/")
    assert d["title"] == "Fika i Stockholm" and d["title_count"] == 2
    assert d["description"] == "Guide to fika."
    assert d["canonical"] == "https://ex.com/fika/" and d["lang"] == "sv" and d["has_viewport"]
    assert d["h1"] == ["Fika"] and [h["level"] for h in d["headings"]] == [1, 3]
    assert d["jsonld_types"] == ["CafeOrCoffeeShop", "Organization"]
    assert len(d["jsonld_errors"]) == 1
    internal = [l for l in d["links"] if l["internal"]]
    assert internal[0]["href"] == "https://ex.com/om-oss"
    assert any(l["nofollow"] and not l["internal"] for l in d["links"])
    assert d["images"][0]["alt"] is None and d["images"][1]["alt"] == ""
    assert {v["kind"] for v in d["videos"]} == {"embed", "html5"}
    assert d["phones"] == ["+46 8 123 45"] and d["author"] == "Kshyati"
    assert d["og"]["title"] == "Fika" and d["twitter"]["card"] == "summary"
    assert "not text" not in d["text_sample"] and d["word_count"] >= 15
    assert d["hreflang"] == [{"lang": "en", "href": "https://ex.com/en/fika/"}]


ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /private/public-page
Disallow: /*.pdf$
Disallow: /search?

User-agent: Googlebot
User-agent: Bingbot
Disallow: /no-google/

User-agent: GPTBot
Disallow: /

Sitemap: https://ex.com/sitemap.xml
Bogus line
"""


def test_robots_precedence_and_groups():
    r = robots.parse(ROBOTS)
    assert r.sitemaps == ["https://ex.com/sitemap.xml"] and r.errors
    assert not r.allowed("SomeBot", "/private/x")
    assert r.allowed("SomeBot", "/private/public-page")  # longer allow wins
    assert not r.allowed("SomeBot", "/files/a.pdf") and r.allowed("SomeBot", "/files/a.pdf?x=1")
    assert not r.allowed("SomeBot", "/search?q=1") and r.allowed("SomeBot", "/search")
    assert r.allowed("Googlebot", "/private/x")  # own group replaces *
    assert not r.allowed("Googlebot/2.1", "/no-google/a") and not r.allowed("bingbot", "/no-google/")
    assert r.allowed("Googlebot-Image", "/private/x")  # falls back to Googlebot group
    assert not r.allowed("GPTBot", "/") and r.allowed("GPTBot", "/robots.txt")
    policy = {p["agent"]: p["allowed"] for p in robots.ai_policy(r)}
    assert policy["GPTBot"] is False and policy["OAI-SearchBot"] is True


def test_robots_empty_disallow_and_tie():
    r = robots.parse("User-agent: *\nDisallow:\n")
    assert r.allowed("x", "/anything")
    r = robots.parse("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert r.allowed("x", "/page")


def test_sitemap_parse_and_index():
    index = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://ex.com/a.xml</loc></sitemap></sitemapindex>"""
    urlset = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ex.com/</loc><lastmod>2026-11-01</lastmod></url>
      <url><loc>https://other.com/x</loc><lastmod>01/11/2026</lastmod></url></urlset>"""
    sm = sitemap.parse(index, "https://ex.com/sitemap.xml")
    assert sm.kind == "sitemapindex" and sm.children == ["https://ex.com/a.xml"]
    sm = sitemap.parse(gzip.compress(urlset), "https://ex.com/a.xml")
    assert [u["loc"] for u in sm.urls] == ["https://ex.com/", "https://other.com/x"]
    assert any("W3C" in p for p in sm.problems) and any("different host" in p for p in sm.problems)


def test_sitemap_rejects_entity_bombs_and_bad_xml():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
      <urlset><url><loc>&lol2;</loc></url></urlset>"""
    assert sitemap.parse(bomb).problems
    assert "not valid XML" in sitemap.parse(b"<urlset><url>").problems[0]
    assert "expected" in sitemap.parse(b"<html></html>").problems[0]


def test_sitemap_collect_follows_index():
    from seokit.net import Response

    files = {
        "https://ex.com/sitemap.xml": b'<sitemapindex><sitemap><loc>https://ex.com/a.xml</loc></sitemap>'
                                      b'<sitemap><loc>https://ex.com/missing.xml</loc></sitemap></sitemapindex>',
        "https://ex.com/a.xml": b"<urlset><url><loc>https://ex.com/p</loc></url></urlset>",
    }

    def fetch(u):
        body = files.get(u)
        return Response(url=u, final_url=u, status=200 if body else 404, body=body or b"")

    out = sitemap.collect(["https://ex.com/sitemap.xml"], fetch)
    assert [u["loc"] for u in out["urls"]] == ["https://ex.com/p"]
    assert [f["status"] for f in out["files"]] == [200, 200, 404]
