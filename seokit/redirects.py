#!/usr/bin/env python3
"""
Plan and verify redirects for a site migration or URL restructure.

plan:   match every old URL to its best new URL and write a redirect file for
        Next.js, Vercel, Netlify, nginx, Apache or CSV. Works offline on two
        URL lists (plain text, one URL or path per line, or sitemap XML).
verify: after launch, request every old URL and check it lands on the planned
        page in one permanent hop with a 200.

Usage:
    python run.py redirects plan --old old-sitemap.xml --new new-urls.txt --format next
    python run.py redirects plan --old old.txt --new new.txt --format csv > redirects.csv
    python run.py redirects verify --map redirects.csv --base https://new.example.com
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse


_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_EXT_RE = re.compile(r"\.(html?|php|aspx?|jsp)$", re.I)
_NEXT_SPECIAL = re.compile(r"([:()*?+])")
FORMATS = ("csv", "next", "vercel", "netlify", "nginx", "apache", "json")


# --------------------------------------------------------------------------- input

def read_urls(path: str) -> list[str]:
    """Read a URL list file or a sitemap XML file (locs only, no entity expansion)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if "<loc>" in text.lower():
        items = _LOC_RE.findall(text)
    else:
        items = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def to_path(url: str) -> str:
    """'https://a.com/x/?q=1' -> '/x/?q=1'; a bare path is returned as is."""
    p = urlparse(url)
    path = p.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path + (f"?{p.query}" if p.query else "")


def norm(path: str) -> str:
    """Comparison key: lowercase, no query, no extension, no index, no trailing slash."""
    path = path.split("?", 1)[0].lower()
    path = re.sub(r"/index(\.[a-z]+)?$", "/", path)
    path = _EXT_RE.sub("", path)
    path = path.rstrip("/") or "/"
    return path


def slug(path: str) -> str:
    n = norm(path)
    return n.rsplit("/", 1)[-1] if n != "/" else ""


# --------------------------------------------------------------------------- matching

def plan(old_urls: list[str], new_urls: list[str], threshold: float = 0.6) -> dict:
    new_paths = [to_path(u) for u in new_urls]
    new_raw = set(new_paths)
    by_norm = {norm(p): p for p in new_paths}
    by_slug: dict[str, list[str]] = {}
    for p in new_paths:
        if slug(p):
            by_slug.setdefault(slug(p), []).append(p)

    redirects, unchanged, unmatched = [], [], []
    for old in old_urls:
        op = to_path(old)
        if op in new_raw:
            unchanged.append(op)
            continue
        entry = {"old": op, "query": "?" in op}
        key = norm(op)
        if key in by_norm:
            entry.update(new=by_norm[key], confidence=1.0, reason="same page, new URL format")
        elif slug(op) and slug(op) in by_slug:
            cands = by_slug[slug(op)]
            best = max(cands, key=lambda c: difflib.SequenceMatcher(None, key, norm(c)).ratio())
            entry.update(new=best, confidence=0.9 if len(cands) == 1 else 0.75,
                         reason="same slug, moved section" if len(cands) == 1
                         else f"same slug, {len(cands)} candidates; check")
        else:
            scored = [(difflib.SequenceMatcher(None, key, norm(c)).ratio(), c) for c in new_paths]
            score, best = max(scored, default=(0.0, None))
            if best and score >= threshold:
                # A fuzzy match is a guess, so it always lands in the review list.
                entry.update(new=best, confidence=min(round(score, 2), 0.85), reason="similar URL; check")
            else:
                parent = _nearest_parent(key, by_norm)
                if parent:
                    entry.update(new=parent, confidence=0.3,
                                 reason="no match; nearest parent section. Prefer a real equivalent page")
                else:
                    unmatched.append(op)
                    continue
        redirects.append(entry)

    _flatten_chains(redirects)
    return {
        "redirects": redirects,
        "unchanged": unchanged,
        "unmatched": unmatched,
        "summary": {
            "old_urls": len(old_urls),
            "redirects": len(redirects),
            "unchanged": len(unchanged),
            "unmatched": len(unmatched),
            "needs_review": sum(1 for r in redirects if r["confidence"] < 0.9),
        },
    }


def _nearest_parent(key: str, by_norm: dict[str, str]) -> Optional[str]:
    parts = key.strip("/").split("/")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "/" + "/".join(parts[:i])
        if candidate in by_norm:
            return by_norm[candidate]
    return None


def _flatten_chains(redirects: list[dict]) -> None:
    """If a target is itself redirected, point straight at the final page."""
    table = {r["old"]: r["new"] for r in redirects}
    for r in redirects:
        seen, target = {r["old"]}, r["new"]
        while target in table and target not in seen:
            seen.add(target)
            target = table[target]
        if target != r["new"]:
            r["new"] = target
            r["reason"] += "; chain flattened"


# --------------------------------------------------------------------------- output

def _next_src(path: str) -> str:
    return _NEXT_SPECIAL.sub(r"\\\1", path.split("?", 1)[0])


def render(result: dict, fmt: str) -> str:
    rows = result["redirects"]
    if fmt == "json":
        return json.dumps(result, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["old", "new", "status", "confidence", "reason"])
        for r in rows:
            w.writerow([r["old"], r["new"], 301, r["confidence"], r["reason"]])
        return buf.getvalue()
    if fmt == "next":
        body = ",\n".join(
            f"      {{ source: {json.dumps(_next_src(r['old']))}, "
            f"destination: {json.dumps(r['new'])}, permanent: true }}"
            for r in rows
        )
        return ("// Add to next.config.js\nmodule.exports = {\n  async redirects() {\n    return [\n"
                + body + "\n    ];\n  },\n};\n")
    if fmt == "vercel":
        return json.dumps({"redirects": [
            {"source": _next_src(r["old"]), "destination": r["new"], "permanent": True} for r in rows
        ]}, indent=2) + "\n"
    if fmt == "netlify":
        return "".join(f"{r['old'].split('?', 1)[0]}  {r['new']}  301\n" for r in rows)
    if fmt == "nginx":
        return "".join(
            f"location = {r['old'].split('?', 1)[0]} {{ return 301 {r['new']}; }}\n" for r in rows
        )
    if fmt == "apache":
        return "".join(f"Redirect 301 {r['old'].split('?', 1)[0]} {r['new']}\n" for r in rows)
    raise ValueError(f"unknown format {fmt}")


# --------------------------------------------------------------------------- verify

def read_map(path: str) -> list[tuple[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [(row["old"].strip(), row["new"].strip()) for row in reader if row.get("old")]


def verify(pairs: list[tuple[str, str]], base: str, timeout: int = 20, fetch=None) -> dict:
    if fetch is None:
        from .net import fetch
    results = []
    for old, new in pairs:
        url = old if urlparse(old).scheme else urljoin(base, old)
        res = fetch(url, timeout=timeout, max_redirects=10)
        if not isinstance(res, dict):  # a net.Response
            res = {"error": res.error, "status_code": res.status, "url": res.final_url,
                   "redirect_details": [{"url": u, "status_code": c} for u, c in res.redirects]}
        hops = res.get("redirect_details") or []
        final = res.get("url") or url
        expected = new if urlparse(new).scheme else urljoin(base, new)
        problems = []
        if res.get("error"):
            problems.append(f"error: {res['error']}")
        else:
            if res.get("status_code") != 200:
                problems.append(f"lands on HTTP {res.get('status_code')}")
            if norm(to_path(final)) != norm(to_path(expected)):
                problems.append(f"lands on {to_path(final)}, expected {to_path(expected)}")
            if not hops:
                problems.append("no redirect")
            else:
                if len(hops) > 1:
                    problems.append(f"{len(hops)} hops; make it one")
                if hops[0].get("status_code") not in (301, 308):
                    problems.append(f"first hop is {hops[0].get('status_code')}, use 301 or 308")
        results.append({"old": old, "expected": to_path(expected), "final": to_path(final),
                        "status": res.get("status_code"), "hops": len(hops), "ok": not problems,
                        "problems": problems})
    ok = sum(1 for r in results if r["ok"])
    return {"checked": len(results), "ok": ok, "failed": len(results) - ok,
            "results": [r for r in results if not r["ok"]] + [r for r in results if r["ok"]]}


# --------------------------------------------------------------------------- cli

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Plan and verify migration redirects.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="Match old URLs to new URLs and write redirects")
    p.add_argument("--old", required=True, help="Old URLs: text list or sitemap XML")
    p.add_argument("--new", required=True, help="New URLs: text list or sitemap XML")
    p.add_argument("--format", choices=FORMATS, default="csv")
    p.add_argument("--threshold", type=float, default=0.6, help="Fuzzy match cut-off (0 to 1)")
    p.add_argument("--report", help="Also write the full JSON report to this file")
    v = sub.add_parser("verify", help="Check live redirects against a CSV map")
    v.add_argument("--map", required=True, help="CSV with old,new columns (from plan --format csv)")
    v.add_argument("--base", required=True, help="Origin to request relative old paths on")
    v.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args(argv)

    if args.cmd == "plan":
        result = plan(read_urls(args.old), read_urls(args.new), args.threshold)
        sys.stdout.write(render(result, args.format))
        if args.report:
            Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
        s = result["summary"]
        print(f"redirects: {s['redirects']} redirects, {s['unchanged']} unchanged, "
              f"{s['unmatched']} unmatched, {s['needs_review']} to review", file=sys.stderr)
        return 0

    report = verify(read_map(args.map), args.base, args.timeout)
    print(json.dumps(report, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
