"""seokit/logs.py: crawler activity from access logs."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from seokit import logs as la

GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
LINES = [
    f'66.249.66.1 - - [10/Nov/2026:10:00:00 +0000] "GET /blog/a HTTP/1.1" 200 512 "-" "{GBOT}"',
    f'66.249.66.1 - - [10/Nov/2026:10:01:00 +0000] "GET /blog/a?sort=new HTTP/1.1" 200 512 "-" "{GBOT}"',
    f'66.249.66.1 - - [11/Nov/2026:10:02:00 +0000] "GET /old HTTP/1.1" 301 0 "-" "{GBOT}"',
    f'66.249.66.1 - - [11/Nov/2026:10:03:00 +0000] "GET /missing HTTP/1.1" 404 0 "-" "{GBOT}"',
    f'66.249.66.1 - - [11/Nov/2026:10:04:00 +0000] "GET /_next/static/app.js HTTP/1.1" 200 0 "-" "{GBOT}"',
    '1.2.3.4 - - [11/Nov/2026:10:05:00 +0000] "GET /blog/a HTTP/1.1" 200 1 "-" "Mozilla/5.0 (compatible; GPTBot/1.2)"',
    '1.2.3.5 - - [11/Nov/2026:10:06:00 +0000] "GET / HTTP/1.1" 200 1 "-" "Mozilla/5.0 Firefox/130.0"',
    "garbage line",
]


def test_classify():
    assert la.classify(GBOT) == ("Googlebot", "search")
    assert la.classify("Mozilla/5.0 (compatible; ClaudeBot/1.0)") == ("ClaudeBot", "ai-training")
    assert la.classify("Mozilla/5.0 ChatGPT-User/1.0") == ("ChatGPT-User", "ai-user")
    assert la.classify("OAI-SearchBot/1.0") == ("OAI-SearchBot", "ai-search")
    assert la.classify("Mozilla/5.0 (compatible; AhrefsBot/7.0)") == ("AhrefsBot", "seo-tool")
    assert la.classify("Mozilla/5.0 Safari") == ("Human or unknown", "human")


def test_parse_combined_and_json():
    r = la.parse_line(LINES[0])
    assert r == {"ip": "66.249.66.1", "path": "/blog/a", "status": 200, "ua": GBOT, "day": "2026-11-10"}
    vercel = json.dumps({"timestamp": 1794650400000, "proxy": {"path": "/x", "userAgent": [GBOT],
                                                               "statusCode": 200, "clientIp": "66.249.66.2"}})
    v = la.parse_line(vercel)
    assert v["path"] == "/x" and v["status"] == 200 and v["ua"] == GBOT and v["day"].startswith("2026")
    cf = json.dumps({"ClientRequestURI": "/y?z=1", "ClientRequestUserAgent": "GPTBot",
                     "EdgeResponseStatus": 404, "ClientIP": "1.1.1.1", "EdgeStartTimestamp": "2026-11-12T01:02:03Z"})
    c = la.parse_line(cf)
    assert c["path"] == "/y?z=1" and c["status"] == 404 and c["day"] == "2026-11-12"
    assert la.parse_line("garbage line") is None


def test_waste_reasons():
    assert la.waste_reason("/a?x=1", 200) == "parameter"
    assert la.waste_reason("/api/x", 200) == "api"
    assert la.waste_reason("/img/a.webp", 200) == "asset"
    assert la.waste_reason("/a", 301) == "redirect"
    assert la.waste_reason("/a", 404) == "client-error"
    assert la.waste_reason("/a", 503) == "server-error"
    assert la.waste_reason("/a", 200) is None


def test_analyse_report_and_sitemap(tmp_path):
    log = tmp_path / "access.log.gz"
    with gzip.open(log, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(LINES))
    records = [r for r in map(la.parse_line, la.read_lines([str(log)])) if r]
    report = la.analyse(records, sitemap_paths=["/blog/a", "/blog/b", "/"])
    assert report["total_hits"] == 7
    g = next(c for c in report["crawlers"] if c["crawler"] == "Googlebot")
    assert g["hits"] == 5 and g["wasted_hits"] == 4 and g["wasted_pct"] == 80.0
    assert g["status"] == {"2xx": 3, "3xx": 1, "4xx": 1}
    assert g["top_errors"] == [("404 /missing", 1)]
    assert g["daily_hits"] == {"2026-11-10": 2, "2026-11-11": 3}
    assert report["sitemap_pages_not_crawled_by_googlebot"] == ["/blog/b", "/"]


def test_bot_filter_and_dns_verification(monkeypatch):
    records = [la.parse_line(line) for line in LINES[:2]]

    def fake_reverse(ip):
        return ("crawl-66-249-66-1.googlebot.com", [], [ip]) if ip == "66.249.66.1" else ("evil.example", [], [])

    monkeypatch.setattr(la.socket, "gethostbyaddr", fake_reverse)
    monkeypatch.setattr(la.socket, "gethostbyname_ex", lambda host: (host, [], ["66.249.66.1"]))
    report = la.analyse(records, only_bot="googlebot", verify_dns=True)
    g = report["crawlers"][0]
    assert g["fake_hits"] == 0 and g["dns_checked_ips"] == 1

    fake = la.parse_line(LINES[0].replace("66.249.66.1", "9.9.9.9"))
    report = la.analyse([fake], verify_dns=True)
    assert report["crawlers"][0]["fake_ips"] == ["9.9.9.9"]


def test_cli_text(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text("\n".join(LINES), encoding="utf-8")
    assert la.main([str(log)]) == 0
    out = capsys.readouterr().out
    assert "Googlebot top paths:" in out and "GPTBot" in out
