#!/usr/bin/env python3
"""
Pre-deploy SEO gate: fail a build when SEO-critical tags break.

Checks a folder of built HTML (Next.js `out/`, Astro `dist/`, any static
export) or a list of live URLs. Every page gets the same rules: title,
meta description, robots noindex, canonical, H1, html lang, JSON-LD validity
and hreflang self-reference. Across pages it flags duplicate titles and
descriptions.

Usage:
    python run.py ci --dir out/ [--base-url https://example.com]
    python run.py ci https://example.com/ https://example.com/pricing
    python run.py ci --urls-file urls.txt --fail-on warning --json
    SEOKIT_ALLOW_HOSTS=localhost:3000 python run.py ci --sitemap sitemap.xml \\
        --origin http://localhost:3000 --base-url https://example.com

Exit codes: 0 pass, 1 findings at or above --fail-on, 2 usage error.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse


from .extract import extract

SEVERITY_RANK = {"warning": 1, "error": 2}
TITLE_MAX = 60
DESCRIPTION_MAX = 160
# Error pages are meant to be noindex, so they never fail the noindex rule.
DEFAULT_NOINDEX_ALLOW = ("/404*", "/500*", "/_error*", "/_not-found*")
SKIP_DIRS = {"_next", "_astro", "node_modules", ".git", "assets", "static"}
_LANG_RE = re.compile(r"<html\b[^>]*\blang\s*=\s*[\"']?([A-Za-z][A-Za-z0-9-]*)", re.I)


def finding(severity: str, rule: str, message: str) -> dict:
    return {"severity": severity, "rule": rule, "message": message}


def path_for_file(root: Path, file: Path) -> str:
    """Map a built HTML file to the URL path it is served at."""
    rel = file.relative_to(root).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel[: -len(".html")]


def collect_html_files(root: Path, limit: int) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".html"):
                files.append(Path(dirpath) / name)
                if len(files) >= limit:
                    return files
    return files


def _same_page(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.netloc.lower(), pa.path.rstrip("/") or "/") == (
        pb.netloc.lower(),
        pb.path.rstrip("/") or "/",
    )


def check_page(
    html: str,
    page: str,
    page_url: Optional[str],
    noindex_allow: tuple[str, ...],
    base_host: Optional[str],
    headers: Optional[dict] = None,
) -> tuple[dict, list[dict]]:
    """Run the per-page rules. Returns (parsed summary, findings)."""
    data = extract(html, page_url or "")
    out: list[dict] = []

    title = (data.get("title") or "").strip()
    if not title:
        out.append(finding("error", "title-missing", "No <title>, or it is empty."))
    elif len(title) > TITLE_MAX:
        out.append(finding("warning", "title-long",
                           f"Title is {len(title)} characters; Google shows about {TITLE_MAX}."))

    desc = (data.get("description") or "").strip()
    if not desc:
        out.append(finding("warning", "description-missing", "No meta description."))
    elif len(desc) > DESCRIPTION_MAX:
        out.append(finding("warning", "description-long",
                           f"Meta description is {len(desc)} characters; keep it under {DESCRIPTION_MAX}."))

    robots = (data.get("robots") or "").lower()
    header_robots = ""
    for key, value in (headers or {}).items():
        if key.lower() == "x-robots-tag":
            header_robots = str(value).lower()
    allowed = any(fnmatch.fnmatch(page, pat) for pat in noindex_allow)
    if ("noindex" in robots or "noindex" in header_robots) and not allowed:
        source = "meta robots" if "noindex" in robots else "X-Robots-Tag header"
        out.append(finding("error", "noindex",
                           f"Page is noindex ({source}). If that is intended, pass --allow-noindex '{page}'."))

    canonical = (data.get("canonical") or "").strip()
    if not canonical:
        out.append(finding("warning", "canonical-missing", "No rel=canonical."))
    else:
        parsed = urlparse(canonical)
        if not parsed.scheme:
            out.append(finding("warning", "canonical-relative",
                               f"Canonical '{canonical}' is relative; use an absolute URL."))
        elif base_host and parsed.netloc.lower() != base_host:
            out.append(finding("warning", "canonical-offsite",
                               f"Canonical points to {parsed.netloc}, not {base_host}."))

    h1 = [h for h in data.get("h1") or [] if str(h).strip()]
    if not h1:
        out.append(finding("warning", "h1-missing", "No H1 heading."))
    elif len(h1) > 1:
        out.append(finding("warning", "h1-multiple", f"{len(h1)} H1 headings; use one."))

    if not _LANG_RE.search(html[:5000]):
        out.append(finding("warning", "lang-missing", "<html> has no lang attribute."))

    invalid = len(data.get("jsonld_errors") or [])
    if invalid:
        out.append(finding("error", "schema-invalid",
                           f"{invalid} JSON-LD block(s) do not parse. Search engines ignore them."))

    hreflang = data.get("hreflang") or []
    if hreflang:
        self_ref = canonical or page_url or ""
        hrefs = [urljoin(page_url or "", h.get("href") or "") for h in hreflang]
        if self_ref and urlparse(self_ref).netloc and not any(_same_page(h, self_ref) for h in hrefs):
            out.append(finding("warning", "hreflang-no-self",
                               "hreflang set does not include this page itself."))

    summary = {"title": title, "description": desc}
    return summary, out


def site_findings(summaries: dict[str, dict]) -> dict[str, list[dict]]:
    """Duplicate titles and descriptions across pages."""
    extra: dict[str, list[dict]] = defaultdict(list)
    for field, rule in (("title", "title-duplicate"), ("description", "description-duplicate")):
        groups: dict[str, list[str]] = defaultdict(list)
        for page, s in summaries.items():
            if s.get(field):
                groups[s[field].strip().lower()].append(page)
        for pages in groups.values():
            if len(pages) > 1:
                for page in pages:
                    others = ", ".join(p for p in pages if p != page)[:200]
                    extra[page].append(finding("warning", rule, f"Same {field} as {others}."))
    return extra


def run(args: argparse.Namespace) -> dict:
    noindex_allow = DEFAULT_NOINDEX_ALLOW + tuple(args.allow_noindex or ())
    base_host = urlparse(args.base_url).netloc.lower() if args.base_url else None
    pages: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}

    if args.dir:
        root = Path(args.dir)
        if not root.is_dir():
            raise SystemExit(f"--dir {root} is not a folder")
        for file in collect_html_files(root, args.max_pages):
            page = path_for_file(root, file)
            url = urljoin(args.base_url, page) if args.base_url else None
            html = file.read_text(encoding="utf-8", errors="replace")
            summaries[page], pages[page] = check_page(html, page, url, noindex_allow, base_host)
    else:
        from . import net

        urls = list(args.urls or [])
        if args.urls_file:
            urls += [line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
        if args.sitemap:
            from .redirects import read_urls

            urls += read_urls(args.sitemap)
        if not urls:
            raise SystemExit("give --dir, URLs, --urls-file or --sitemap")
        if args.origin:
            # Check production URLs on a local or preview server.
            origin = args.origin.rstrip("/")
            urls = [origin + (urlparse(u).path or "/") + (f"?{urlparse(u).query}" if urlparse(u).query else "")
                    for u in urls]
        for url in urls[: args.max_pages]:
            page = urlparse(url).path or "/"
            host = base_host or urlparse(url).netloc.lower()
            res = net.fetch(url, timeout=args.timeout)
            if res.error or res.status != 200:
                reason = res.error or f"HTTP {res.status}"
                pages[url] = [finding("error", "fetch-failed", f"Could not load page: {reason}.")]
                continue
            summaries[url], pages[url] = check_page(
                res.text, page, res.final_url or url, noindex_allow, host,
                res.headers,
            )

    for page, extra in site_findings(summaries).items():
        pages[page].extend(extra)

    threshold = SEVERITY_RANK[args.fail_on]
    counts = {"error": 0, "warning": 0}
    for items in pages.values():
        for f in items:
            counts[f["severity"]] += 1
    failed = any(SEVERITY_RANK[f["severity"]] >= threshold for items in pages.values() for f in items)
    return {
        "pages_checked": len(pages),
        "counts": counts,
        "fail_on": args.fail_on,
        "passed": not failed,
        "pages": {p: f for p, f in sorted(pages.items()) if f},
    }


def render_text(report: dict) -> str:
    lines = []
    for page, items in report["pages"].items():
        lines.append(page)
        for f in sorted(items, key=lambda f: -SEVERITY_RANK[f["severity"]]):
            mark = "ERROR" if f["severity"] == "error" else "warn "
            lines.append(f"  {mark} {f['rule']}: {f['message']}")
    c = report["counts"]
    verdict = "PASS" if report["passed"] else "FAIL"
    lines.append(f"\n{verdict}: {report['pages_checked']} pages, {c['error']} errors, "
                 f"{c['warning']} warnings (failing on {report['fail_on']}).")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pre-deploy SEO gate for built HTML or live URLs.")
    p.add_argument("urls", nargs="*", help="Live URLs to check")
    p.add_argument("--dir", help="Folder of built HTML (out/, dist/, build/)")
    p.add_argument("--urls-file", help="File with one URL per line")
    p.add_argument("--sitemap", help="Local sitemap XML file whose URLs to check")
    p.add_argument("--origin", help="Request every URL on this origin instead, e.g. http://localhost:3000 "
                                    "(set SEOKIT_ALLOW_HOSTS=localhost:3000 to allow it)")
    p.add_argument("--base-url", help="Production origin, used to resolve canonicals and hosts")
    p.add_argument("--fail-on", choices=("error", "warning"), default="error")
    p.add_argument("--allow-noindex", action="append", metavar="PATTERN",
                   help="Path glob that may be noindex, e.g. '/drafts/*' (repeatable)")
    p.add_argument("--max-pages", type=int, default=2000)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(f"ci_check: {exc.code}", file=sys.stderr)
            return 2
        raise
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
