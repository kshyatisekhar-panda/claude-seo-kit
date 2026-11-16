"""seokit/redirects.py: migration redirect planning and verification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from seokit import redirects as rm


def by_old(result):
    return {r["old"]: r for r in result["redirects"]}


def test_read_urls_from_sitemap_and_list(tmp_path):
    sm = tmp_path / "s.xml"
    sm.write_text("<urlset><url><loc> https://a.com/x </loc></url><url><loc>https://a.com/x</loc></url></urlset>")
    assert rm.read_urls(str(sm)) == ["https://a.com/x"]
    lst = tmp_path / "l.txt"
    lst.write_text("# comment\n/a\n\n/b\n")
    assert rm.read_urls(str(lst)) == ["/a", "/b"]


def test_match_levels():
    old = ["https://old.com/about.html", "https://old.com/2023/05/fika-guide",
           "https://old.com/same", "https://old.com/blog/cinnamon-bun-recipe-2023",
           "https://old.com/shop/discontinued-thing", "https://old.com/zzz"]
    new = ["https://new.com/about", "https://new.com/blog/fika-guide", "https://new.com/same",
           "https://new.com/blog/cinnamon-bun-recipe", "https://new.com/shop"]
    result = rm.plan(old, new)
    r = by_old(result)
    assert r["/about.html"]["new"] == "/about" and r["/about.html"]["confidence"] == 1.0
    assert r["/2023/05/fika-guide"]["new"] == "/blog/fika-guide" and r["/2023/05/fika-guide"]["confidence"] == 0.9
    assert r["/blog/cinnamon-bun-recipe-2023"]["new"] == "/blog/cinnamon-bun-recipe"
    assert r["/shop/discontinued-thing"]["new"] == "/shop" and r["/shop/discontinued-thing"]["confidence"] == 0.3
    assert result["unchanged"] == ["/same"]
    assert result["unmatched"] == ["/zzz"]
    assert result["summary"]["needs_review"] == 2


def test_never_redirects_unrelated_pages_to_home():
    result = rm.plan(["/totally-unrelated-thing"], ["/", "/contact"])
    assert result["unmatched"] == ["/totally-unrelated-thing"]


def test_chains_are_flattened():
    redirects = [{"old": "/a", "new": "/b", "reason": "x"}, {"old": "/b", "new": "/c", "reason": "y"}]
    rm._flatten_chains(redirects)
    assert redirects[0]["new"] == "/c" and "chain flattened" in redirects[0]["reason"]


def test_query_strings_are_flagged():
    result = rm.plan(["/product?id=12"], ["/products/12"])
    assert all(r["query"] for r in result["redirects"])


def test_render_formats():
    result = rm.plan(["/old-page.html", "/a:b"], ["/old-page", "/a-b"], threshold=0.5)
    nxt = rm.render(result, "next")
    assert "permanent: true" in nxt and nxt.rstrip().endswith("};")
    assert '"/a\\\\:b"' in nxt  # colon escaped for path-to-regexp
    vercel = json.loads(rm.render(result, "vercel"))
    assert vercel["redirects"][0]["permanent"] is True
    assert rm.render(result, "netlify").startswith("/old-page.html  /old-page  301")
    assert "return 301 /old-page;" in rm.render(result, "nginx")
    assert rm.render(result, "apache").startswith("Redirect 301 /old-page.html /old-page")
    assert rm.render(result, "csv").splitlines()[0] == "old,new,status,confidence,reason"


def test_verify_checks_hops_status_and_target():
    responses = {
        "https://new.com/good": {"url": "https://new.com/target", "status_code": 200,
                                 "redirect_details": [{"url": "https://new.com/good", "status_code": 301}]},
        "https://new.com/temp": {"url": "https://new.com/target", "status_code": 200,
                                 "redirect_details": [{"url": "https://new.com/temp", "status_code": 302}]},
        "https://new.com/chain": {"url": "https://new.com/target", "status_code": 200,
                                  "redirect_details": [{"status_code": 301}, {"status_code": 301}]},
        "https://new.com/wrong": {"url": "https://new.com/", "status_code": 200,
                                  "redirect_details": [{"status_code": 301}]},
        "https://new.com/none": {"url": "https://new.com/none", "status_code": 404, "redirect_details": []},
    }

    def fake(url, **kw):
        return responses[url]

    pairs = [(p, "/target") for p in ("/good", "/temp", "/chain", "/wrong", "/none")]
    report = rm.verify(pairs, "https://new.com", fetch=fake)
    by = {r["old"]: r for r in report["results"]}
    assert by["/good"]["ok"]
    assert any("302" in p for p in by["/temp"]["problems"])
    assert any("2 hops" in p for p in by["/chain"]["problems"])
    assert any("expected /target" in p for p in by["/wrong"]["problems"])
    assert any("no redirect" in p for p in by["/none"]["problems"])
    assert report["ok"] == 1 and report["failed"] == 4


def test_cli_plan_writes_report(tmp_path, capsys):
    (tmp_path / "old.txt").write_text("/about.html\n")
    (tmp_path / "new.txt").write_text("/about\n")
    rep = tmp_path / "r.json"
    assert rm.main(["plan", "--old", str(tmp_path / "old.txt"), "--new", str(tmp_path / "new.txt"),
                    "--format", "netlify", "--report", str(rep)]) == 0
    assert "/about.html  /about  301" in capsys.readouterr().out
    assert json.loads(rep.read_text())["summary"]["redirects"] == 1
