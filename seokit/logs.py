#!/usr/bin/env python3
"""
Show how search engines and AI crawlers actually crawl a site, from its logs.

Reads access logs in Combined Log Format (nginx, Apache, most hosts) or JSON
lines (Vercel log drains, Cloudflare, Netlify, generic). Plain or .gz files.
For every crawler it reports hits, status codes, top paths, error paths, and
crawl spent on URLs that should not use crawl budget (parameters, assets,
APIs, redirects, errors). With --sitemap it lists important pages Googlebot
never requested.

User agents can be faked. --verify-dns confirms Googlebot and Bingbot hits by
reverse and forward DNS, the method both engines document.

Usage:
    python run.py logs access.log [more.log.gz ...]
    python run.py logs vercel.jsonl --sitemap sitemap.xml --json
    python run.py logs access.log --bot Googlebot --verify-dns
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import urlparse


# (pattern, name, category). First match wins, so specific names come first.
CRAWLERS = [
    (r"Google-InspectionTool", "Google-InspectionTool", "search"),
    (r"GoogleOther", "GoogleOther", "search"),
    (r"Googlebot-Image", "Googlebot-Image", "search"),
    (r"Googlebot", "Googlebot", "search"),
    (r"bingbot", "Bingbot", "search"),
    (r"Applebot", "Applebot", "search"),
    (r"DuckDuckBot", "DuckDuckBot", "search"),
    (r"YandexBot", "YandexBot", "search"),
    (r"Baiduspider", "Baiduspider", "search"),
    (r"OAI-SearchBot", "OAI-SearchBot", "ai-search"),
    (r"Claude-SearchBot", "Claude-SearchBot", "ai-search"),
    (r"PerplexityBot", "PerplexityBot", "ai-search"),
    (r"ChatGPT-User", "ChatGPT-User", "ai-user"),
    (r"Claude-User", "Claude-User", "ai-user"),
    (r"Perplexity-User", "Perplexity-User", "ai-user"),
    (r"GPTBot", "GPTBot", "ai-training"),
    (r"ClaudeBot|anthropic-ai", "ClaudeBot", "ai-training"),
    (r"CCBot", "CCBot", "ai-training"),
    (r"Bytespider", "Bytespider", "ai-training"),
    (r"meta-externalagent", "Meta-ExternalAgent", "ai-training"),
    (r"Amazonbot", "Amazonbot", "ai-training"),
    (r"AhrefsBot", "AhrefsBot", "seo-tool"),
    (r"SemrushBot", "SemrushBot", "seo-tool"),
    (r"MJ12bot", "MJ12bot", "seo-tool"),
    (r"DotBot", "DotBot", "seo-tool"),
    (r"bot|crawl|spider|slurp", "Other bot", "other-bot"),
]
_CRAWLER_RES = [(re.compile(p, re.I), n, c) for p, n, c in CRAWLERS]
DNS_SUFFIXES = {
    "Googlebot": (".googlebot.com", ".google.com", ".googleusercontent.com"),
    "Googlebot-Image": (".googlebot.com", ".google.com"),
    "Bingbot": (".search.msn.com",),
}
_COMBINED = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) \S+(?: "[^"]*" "(?P<ua>[^"]*)")?'
)
_ASSET = re.compile(r"\.(js|mjs|css|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|map|json|xml|txt)$", re.I)


def classify(ua: str) -> tuple[str, str]:
    for rx, name, cat in _CRAWLER_RES:
        if rx.search(ua or ""):
            return name, cat
    return "Human or unknown", "human"


def _parse_time(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    s = str(value)
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    try:
        return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, ""):
            return v
    return None


def parse_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return None
        src = d.get("proxy") if isinstance(d.get("proxy"), dict) else d
        req = src.get("request") if isinstance(src.get("request"), dict) else {}
        headers = req.get("headers") if isinstance(req.get("headers"), dict) else {}
        path = _first(src, "path", "requestPath", "url", "uri", "ClientRequestURI") or _first(req, "path", "url")
        ua = (_first(src, "userAgent", "user_agent", "ua", "ClientRequestUserAgent")
              or _first(headers, "user-agent", "User-Agent") or "")
        status = _first(src, "statusCode", "status", "responseStatusCode", "EdgeResponseStatus")
        if status is None and isinstance(d.get("response"), dict):
            status = d["response"].get("status")
        if not path or status is None:
            return None
        path = urlparse(path).path + (f"?{urlparse(path).query}" if urlparse(path).query else "") \
            if str(path).startswith("http") else str(path)
        return {"ip": _first(src, "clientIp", "ip", "ClientIP", "remote_addr") or "",
                "path": path, "status": int(status), "ua": str(ua),
                "day": _parse_time(_first(d, "timestamp", "time", "date", "EdgeStartTimestamp"))}
    m = _COMBINED.match(line)
    if not m:
        return None
    return {"ip": m["ip"], "path": m["path"], "status": int(m["status"]), "ua": m["ua"] or "",
            "day": _parse_time(m["time"])}


def read_lines(paths: Iterable[str]) -> Iterable[str]:
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh


def waste_reason(path: str, status: int) -> Optional[str]:
    if status >= 500:
        return "server-error"
    if status >= 400:
        return "client-error"
    if 300 <= status < 400:
        return "redirect"
    if "?" in path:
        return "parameter"
    base = path.split("?", 1)[0]
    if base.startswith("/api/"):
        return "api"
    if base.startswith(("/_next/", "/_astro/", "/static/", "/assets/")) or _ASSET.search(base):
        return "asset"
    return None


def verify_ip(ip: str, bot: str, cache: dict) -> Optional[bool]:
    suffixes = DNS_SUFFIXES.get(bot)
    if not suffixes or not ip:
        return None
    if ip in cache:
        return cache[ip]
    ok = False
    try:
        host = socket.gethostbyaddr(ip)[0].lower()
        if host.endswith(suffixes):
            ok = ip in socket.gethostbyname_ex(host)[2]
    except (OSError, UnicodeError):
        ok = False
    cache[ip] = ok
    return ok


def analyse(records: Iterable[dict], only_bot: Optional[str] = None, sitemap_paths=None,
            verify_dns: bool = False, top: int = 10) -> dict:
    stats: dict[str, dict] = defaultdict(lambda: {
        "hits": 0, "category": "", "status": Counter(), "paths": Counter(), "errors": Counter(),
        "waste": Counter(), "days": Counter(), "ips": Counter(),
    })
    total = 0
    for r in records:
        name, cat = classify(r["ua"])
        if only_bot and name.lower() != only_bot.lower():
            continue
        total += 1
        s = stats[name]
        s["hits"] += 1
        s["category"] = cat
        s["status"][f"{r['status'] // 100}xx"] += 1
        s["paths"][r["path"]] += 1
        if r["status"] >= 400:
            s["errors"][f"{r['status']} {r['path']}"] += 1
        reason = waste_reason(r["path"], r["status"])
        if reason:
            s["waste"][reason] += 1
        if r.get("day"):
            s["days"][r["day"]] += 1
        if r.get("ip"):
            s["ips"][r["ip"]] += 1

    cache: dict = {}
    crawlers = []
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1]["hits"]):
        entry = {
            "crawler": name,
            "category": s["category"],
            "hits": s["hits"],
            "share_pct": round(s["hits"] / total * 100, 1) if total else 0,
            "unique_paths": len(s["paths"]),
            "status": dict(sorted(s["status"].items())),
            "wasted_hits": sum(s["waste"].values()),
            "wasted_pct": round(sum(s["waste"].values()) / s["hits"] * 100, 1),
            "waste_by_reason": dict(s["waste"].most_common()),
            "top_paths": s["paths"].most_common(top),
            "top_errors": s["errors"].most_common(top),
            "daily_hits": dict(sorted(s["days"].items())),
        }
        if verify_dns and name in DNS_SUFFIXES:
            checked = [ip for ip, _ in s["ips"].most_common(50)]
            fake = [ip for ip in checked if verify_ip(ip, name, cache) is False]
            entry["dns_checked_ips"] = len(checked)
            entry["fake_ips"] = fake
            entry["fake_hits"] = sum(s["ips"][ip] for ip in fake)
        crawlers.append(entry)

    report = {"total_hits": total, "crawlers": crawlers}
    if sitemap_paths is not None:
        google = stats.get("Googlebot", {}).get("paths", Counter())
        crawled = {p.split("?", 1)[0].rstrip("/") or "/" for p in google}
        missing = [p for p in sitemap_paths if (p.split("?", 1)[0].rstrip("/") or "/") not in crawled]
        report["sitemap_pages"] = len(sitemap_paths)
        report["sitemap_pages_not_crawled_by_googlebot"] = missing
    return report


def render_text(report: dict) -> str:
    lines = [f"{report['total_hits']} requests", ""]
    lines.append(f"{'crawler':<22}{'type':<13}{'hits':>8}{'share':>8}{'wasted':>9}  status")
    for c in report["crawlers"]:
        status = " ".join(f"{k}:{v}" for k, v in c["status"].items())
        lines.append(f"{c['crawler']:<22}{c['category']:<13}{c['hits']:>8}{c['share_pct']:>7}%"
                     f"{c['wasted_pct']:>8}%  {status}")
        if c.get("fake_hits"):
            lines.append(f"{'':<22}{c['fake_hits']} hits from {len(c['fake_ips'])} IPs failed DNS checks (fake)")
    google = next((c for c in report["crawlers"] if c["crawler"] == "Googlebot"), None)
    if google:
        lines += ["", "Googlebot top paths:"] + [f"  {n:>6}  {p}" for p, n in google["top_paths"]]
        if google["top_errors"]:
            lines += ["Googlebot errors:"] + [f"  {n:>6}  {p}" for p, n in google["top_errors"]]
    if "sitemap_pages_not_crawled_by_googlebot" in report:
        miss = report["sitemap_pages_not_crawled_by_googlebot"]
        lines += ["", f"{len(miss)} of {report['sitemap_pages']} sitemap pages never requested by Googlebot"]
        lines += [f"  {p}" for p in miss[:20]]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Analyse crawler activity in access logs.")
    ap.add_argument("logs", nargs="+", help="Log files (.log, .jsonl, .gz)")
    ap.add_argument("--bot", help="Only this crawler, e.g. Googlebot")
    ap.add_argument("--sitemap", help="Sitemap XML or URL list (local file) to find uncrawled pages")
    ap.add_argument("--verify-dns", action="store_true", help="Confirm Googlebot/Bingbot IPs by DNS")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    sitemap_paths = None
    if args.sitemap:
        from .redirects import read_urls, to_path
        sitemap_paths = [to_path(u) for u in read_urls(args.sitemap)]
    records = (r for r in map(parse_line, read_lines(args.logs)) if r)
    report = analyse(records, args.bot, sitemap_paths, args.verify_dns, args.top)
    if report["total_hits"] == 0:
        print("log_analyze: no lines parsed. Check the log format.", file=sys.stderr)
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
