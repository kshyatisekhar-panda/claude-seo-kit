"""End-to-end audit against a local site, plus rule and scoring units."""

from __future__ import annotations

import json

import pytest

from seokit import findings as fmod
from seokit.audit import audit, page_report
from seokit.findings import Finding
from seokit.rules import performance, schema
from tests.site_server import Site, page

CAFE_SCHEMA = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"CafeOrCoffeeShop",'
               '"name":"Bulle","address":{"@type":"PostalAddress","streetAddress":"Gatan 1",'
               '"addressLocality":"Stockholm"},"aggregateRating":{"@type":"AggregateRating","ratingValue":5}}'
               '</script>')
LONG = " ".join(["Kanelbullar och kaffe smakar bäst tillsammans med vänner."] * 40)


@pytest.fixture
def site(monkeypatch):
    s = Site({
        "/": (200, {}, page("Bulle Cafe Stockholm | Bulle",
                            "<h1>Bulle</h1><p>Cafe in Stockholm.</p><a href='/menu'>Menu</a>"
                            "<a href='/blog/fika'>Fika</a><a href='/old'>Old</a><a href='/gone'>Gone</a>"
                            "<a href='/private/x'>P</a><a href='tel:+4681234567'>Call</a>"
                            "<a href='https://maps.google.com/?q=bulle'>Map</a>",
                            head=CAFE_SCHEMA, canonical="{base}/")),
        "/menu": (200, {}, page("Menu | Bulle", "<h1>Menu</h1><h2>Coffee</h2><p>" + LONG + "</p>"
                                "<a href='tel:+46 70 999 88 77'>Mobile</a>", canonical="{base}/menu")),
        "/blog/fika": (200, {}, page("Menu | Bulle", "<h1>Fika</h1><h1>Again</h1><img src='/a.jpg'><p>"
                                     + LONG + "</p>", desc="A clear description of this page.")),
        "/old": (301, {"Location": "/menu"}, ""),
        "/noindex": (200, {}, page("Hidden", "<h1>x</h1>", head='<meta name="robots" content="noindex">')),
        "/robots.txt": (200, {"Content-Type": "text/plain"},
                        "User-agent: *\nDisallow: /private/\n\nUser-agent: OAI-SearchBot\nDisallow: /\n"
                        "Sitemap: {base}/sitemap.xml\n"),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"},
                         "<urlset><url><loc>{base}/</loc></url><url><loc>{base}/old</loc></url>"
                         "<url><loc>{base}/noindex</loc></url></urlset>"),
    })
    # bodies may mention {base}; fill it in
    for path, (code, headers, body) in list(s.routes.items()):
        s.routes[path] = (code, headers, body.replace("{base}", s.base))
    monkeypatch.setenv("SEOKIT_ALLOW_HOSTS", f"127.0.0.1:{s.port}")
    yield s
    s.close()


def ids(result):
    return {f["id"]: f for f in result["findings"]}


def test_full_audit(site):
    result = audit(site.base + "/", max_pages=20, delay=0, log=lambda m: None)
    assert "error" not in result, result
    got = ids(result)
    json.dumps(result)  # must be serialisable
    urls = {p["url"] for p in result["pages"]}
    assert {site.base + "/", site.base + "/menu", site.base + "/blog/fika", site.base + "/noindex"} <= urls
    assert "/private/x" not in site.hits  # robots.txt respected
    assert got["broken-internal-link"]["pages"] == [site.base + "/gone"]
    assert site.base + "/old" in got["sitemap-non-200"]["pages"]
    assert site.base + "/noindex" in got["sitemap-noindex"]["pages"]
    assert set(got["title-duplicate"]["pages"]) == {site.base + "/menu", site.base + "/blog/fika"}
    assert "h1-multiple" in got and "img-alt-missing" in got and "author-missing" in got
    assert got["ai-search-partly-blocked"]["detail"].startswith("Blocked: OAI-SearchBot")
    assert result["business_type"] == "local" and "local" in result["scores"]
    assert "local-nap-phone" in got and "schema-self-serving-reviews" in got
    assert "local-address-incomplete" in got  # postalCode and country missing
    assert "https-missing" in got  # the test server is plain http
    assert 0 <= result["score"] <= 100


def test_page_report(site):
    r = page_report(site.base + "/blog/fika")
    assert r["status"] == 200 and r["h1"] == ["Fika", "Again"]
    assert {f["id"] for f in r["findings"]} >= {"h1-multiple", "img-alt-missing", "canonical-missing"}


def test_unreachable_site():
    r = audit("http://127.0.0.1:9/", log=lambda m: None)
    assert "error" in r


def test_scoring_spreads_and_clamps():
    one = [Finding("x", "technical", "high", "t", pages=["/a"])]
    many = [Finding("x", "technical", "high", "t", pages=[f"/{i}" for i in range(10)])]
    s1 = fmod.area_scores(one, 10, ["technical"])["technical"]
    s10 = fmod.area_scores(many, 10, ["technical"])["technical"]
    assert 100 > s1 > s10
    worst = [Finding(str(i), "technical", "critical", "t") for i in range(10)]
    assert fmod.area_scores(worst, 1, ["technical"])["technical"] == 0
    assert fmod.overall_score({"technical": 100, "content": 0}) == round(100 * 0.28 / 0.52)


def test_collector_merges_pages():
    c = fmod.Collector()
    c.add(Finding("a", "content", "low", "t"), "/1")
    c.add(Finding("a", "content", "low", "t"), "/2")
    c.add(Finding("b", "content", "critical", "t"), "/1")
    out = c.all()
    assert [f.id for f in out] == ["b", "a"] and out[1].pages == ["/1", "/2"]


def test_schema_requirements():
    probs = {i for _, i, _ in schema.check_object({"@type": "Product", "name": "Mug"})}
    assert "product-snippet" in probs and "product-recommended" in probs
    probs = {i for _, i, _ in schema.check_object({"@type": "Event", "name": "Gig"})}
    assert "event-required" in probs
    probs = {i for _, i, _ in schema.check_object({"@type": "HowTo", "name": "x"})}
    assert "retired-howto" in probs
    ok = schema.check_object({"@type": "VideoObject", "name": "v", "thumbnailUrl": "t", "uploadDate": "2026-01-01",
                              "description": "d", "duration": "PT1M", "contentUrl": "c", "embedUrl": "e"})
    assert ok == []


def test_cwv_rating():
    assert performance.rate("LCP", 2500) == "good"
    assert performance.rate("LCP", 3000) == "needs-improvement"
    assert performance.rate("INP", 501) == "poor"
    assert performance.rate("CLS", 0.1) == "good"


def test_psi_parse():
    from seokit import psi

    data = {"loadingExperience": {"metrics": {
        "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3100},
        "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 30}}},
        "lighthouseResult": {"categories": {"performance": {"score": 0.42}},
                             "audits": {"largest-contentful-paint": {"numericValue": 4200.5}}}}
    out = psi.parse(data, "https://ex.com/")
    assert out["field"] == {"LCP": 3100, "INP": 180, "CLS": 0.3} and out["field_scope"] == "page"
    assert out["lab_score"] == 42 and out["lab"]["LCP"] == 4200.5
    site = {"pages": [], "psi": out}
    got = []
    performance.site_rules(site, lambda f, page="": got.append(f))
    assert {f.id: f.severity for f in got} == {"cwv-lcp": "medium", "cwv-cls": "high", "perf-lab-score": "medium"}


def test_redirect_verify_with_real_responses(site):
    from seokit import redirects

    report = redirects.verify([("/old", "/menu")], site.base)
    assert report["ok"] == 1, report
