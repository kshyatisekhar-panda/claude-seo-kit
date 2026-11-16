"""seokit/ci.py: the pre-deploy SEO gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from seokit import ci as ci_check

GOOD = """<!doctype html><html lang="en"><head>
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="https://example.com{path}">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebPage"}}</script>
</head><body><h1>Heading</h1><p>Body text.</p></body></html>"""


def page(path="/", title="A good title", desc="A good description of the page."):
    return GOOD.format(title=title, desc=desc, path=path)


def write(root: Path, rel: str, html: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(html, encoding="utf-8")


def rules(report: dict, page_key: str) -> set[str]:
    return {f["rule"] for f in report["pages"].get(page_key, [])}


def run(tmp_path, *extra):
    code = ci_check.main(["--dir", str(tmp_path), "--base-url", "https://example.com", "--json", *extra])
    return code


def test_path_mapping(tmp_path):
    assert ci_check.path_for_file(tmp_path, tmp_path / "index.html") == "/"
    assert ci_check.path_for_file(tmp_path, tmp_path / "blog" / "index.html") == "/blog/"
    assert ci_check.path_for_file(tmp_path, tmp_path / "about.html") == "/about"


def test_clean_site_passes(tmp_path, capsys):
    write(tmp_path, "index.html", page("/", "Home page title", "Home description text."))
    write(tmp_path, "about/index.html", page("/about/", "About us title", "About description text."))
    assert run(tmp_path) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] and report["counts"] == {"error": 0, "warning": 0}


def test_noindex_and_missing_title_fail(tmp_path, capsys):
    write(tmp_path, "index.html", page().replace("<title>A good title</title>", ""))
    write(tmp_path, "pricing/index.html",
          page("/pricing/", "Pricing title", "Pricing description.").replace(
              "<head>", '<head><meta name="robots" content="noindex">'))
    assert run(tmp_path) == 1
    report = json.loads(capsys.readouterr().out)
    assert "title-missing" in rules(report, "/")
    assert "noindex" in rules(report, "/pricing/")


def test_error_pages_and_allowlist_may_be_noindex(tmp_path, capsys):
    noindex = page("/404", "Not found", "Not found.").replace("<head>", '<head><meta name="robots" content="noindex">')
    write(tmp_path, "404.html", noindex)
    write(tmp_path, "drafts/x/index.html", noindex.replace("Not found", "Draft x"))
    assert run(tmp_path, "--allow-noindex", "/drafts/*") == 0
    capsys.readouterr()


def test_broken_json_ld_is_an_error(tmp_path, capsys):
    write(tmp_path, "index.html", page().replace('"@type":"WebPage"}', '"@type":"WebPage",}'))
    assert run(tmp_path) == 1
    assert "schema-invalid" in rules(json.loads(capsys.readouterr().out), "/")


def test_warnings_only_fail_with_strict_mode(tmp_path, capsys):
    html = page().replace('<link rel="canonical" href="https://example.com/">', "").replace(' lang="en"', "")
    write(tmp_path, "index.html", html)
    assert run(tmp_path) == 0
    report = json.loads(capsys.readouterr().out)
    assert {"canonical-missing", "lang-missing"} <= rules(report, "/")
    assert run(tmp_path, "--fail-on", "warning") == 1
    capsys.readouterr()


def test_duplicates_offsite_canonical_and_h1(tmp_path, capsys):
    write(tmp_path, "a.html", page("/a").replace("<h1>Heading</h1>", ""))
    write(tmp_path, "b.html", page("/b").replace("https://example.com/b", "https://other.example/b")
          .replace("<h1>Heading</h1>", "<h1>One</h1><h1>Two</h1>"))
    run(tmp_path)
    report = json.loads(capsys.readouterr().out)
    assert {"title-duplicate", "description-duplicate", "h1-missing"} <= rules(report, "/a")
    assert {"canonical-offsite", "h1-multiple"} <= rules(report, "/b")


def test_hreflang_without_self_reference(tmp_path, capsys):
    html = page("/en/").replace(
        "</head>", '<link rel="alternate" hreflang="sv" href="https://example.com/sv/"></head>')
    write(tmp_path, "en/index.html", html)
    run(tmp_path)
    assert "hreflang-no-self" in rules(json.loads(capsys.readouterr().out), "/en/")


def test_url_mode_reports_fetch_failure(monkeypatch, capsys):
    from seokit import net

    monkeypatch.setattr(net, "fetch", lambda url, timeout=20: net.Response(url=url, status=404))
    assert ci_check.main(["https://example.com/missing", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert "fetch-failed" in rules(report, "https://example.com/missing")


def test_origin_rewrite_uses_local_server(monkeypatch, tmp_path, capsys):
    from seokit import net

    seen = []

    def fake(url, timeout=20):
        seen.append(url)
        return net.Response(url=url, final_url=url, status=200, text=page("/x"))

    monkeypatch.setattr(net, "fetch", fake)
    sm = tmp_path / "sitemap.xml"
    sm.write_text("<urlset><url><loc>https://example.com/x</loc></url></urlset>", encoding="utf-8")
    ci_check.main(["--sitemap", str(sm), "--origin", "http://localhost:3000",
                   "--base-url", "https://example.com", "--json"])
    assert seen == ["http://localhost:3000/x"]
    report = json.loads(capsys.readouterr().out)
    assert report["passed"]


def test_usage_error_exit_code(capsys):
    assert ci_check.main(["--json"]) == 2
