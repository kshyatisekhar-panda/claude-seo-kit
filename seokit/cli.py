"""Command line: python run.py <command> [options]. Analysis commands print JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit

from . import __version__, net
from . import robots as robots_mod
from . import sitemap as sitemap_mod

TOOLS = {"ci": "ci", "redirects": "redirects", "decay": "decay", "logs": "logs", "report": "report"}


def _print(data, output: Optional[str] = None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"wrote {output}", file=sys.stderr)
    else:
        print(text)


def cmd_audit(a) -> int:
    from .audit import audit

    result = audit(a.url, max_pages=a.max_pages, with_psi=a.psi, delay=a.delay)
    _print(result, a.output)
    if a.output and "error" not in result:
        c = result["counts"]
        print(f"score {result['score']}/100, {result['pages_crawled']} pages: {c['critical']} critical, "
              f"{c['high']} high, {c['medium']} medium, {c['low']} low")
    return 1 if "error" in result else 0


def cmd_page(a) -> int:
    from .audit import page_report

    result = page_report(a.url, with_psi=a.psi, with_text=a.text)
    _print(result, a.output)
    return 1 if "error" in result else 0


def cmd_robots(a) -> int:
    p = urlsplit(a.url)
    origin = f"{p.scheme}://{p.netloc}"
    res = net.fetch(urljoin(origin, "/robots.txt"))
    out = {"url": urljoin(origin, "/robots.txt"), "status": res.status, "error": res.error}
    if res.status == 200:
        r = robots_mod.parse(res.text)
        out.update(groups=[{"agents": g.agents, "rules": [("allow" if al else "disallow", pat)
                                                         for al, pat in g.rules]} for g in r.groups],
                   sitemaps=r.sitemaps, errors=r.errors, ai_policy=robots_mod.ai_policy(r))
        if a.test:
            agents = robots_mod.SEARCH_AGENTS + [x[0] for x in robots_mod.AI_AGENTS]
            out["test"] = {path: {ag: r.allowed(ag, path) for ag in agents} for path in a.test}
    _print(out)
    return 0


def cmd_sitemap(a) -> int:
    p = urlsplit(a.url)
    origin = f"{p.scheme}://{p.netloc}"
    if p.path.endswith((".xml", ".gz")):
        starts = [a.url]
    else:
        rr = net.fetch(urljoin(origin, "/robots.txt"))
        listed = robots_mod.parse(rr.text).sitemaps if rr.status == 200 else []
        starts = sitemap_mod.default_locations(origin, listed)
    session = net.new_session()
    result = sitemap_mod.collect(starts, lambda u: net.fetch(u, session=session), max_urls=a.max_urls)
    checks = []
    for entry in result["urls"][: a.check]:
        res = net.fetch(entry["loc"], session=session, max_redirects=0)
        item = {"url": entry["loc"], "status": res.status, "error": res.error}
        if res.ok and "html" in res.header("content-type"):
            from .extract import extract

            page = extract(res.text, entry["loc"])
            item.update(noindex="noindex" in (page["robots"] + res.header("x-robots-tag").lower()),
                        canonical=page["canonical"])
        checks.append(item)
    if a.list:
        Path(a.list).write_text("".join(u["loc"] + "\n" for u in result["urls"]), encoding="utf-8")
        print(f"wrote {len(result['urls'])} URLs to {a.list}", file=sys.stderr)
    _print({"starts": starts, "files": result["files"], "url_count": len(result["urls"]),
            "truncated": result["truncated"], "sample": result["urls"][:20], "checked": checks})
    return 0


def cmd_schema(a) -> int:
    from .extract import extract
    from .rules.schema import check_object

    if Path(a.target).is_file():
        html, url = Path(a.target).read_text(encoding="utf-8", errors="replace"), ""
    else:
        res = net.fetch(a.target)
        if not res.ok:
            _print({"url": a.target, "error": res.error or f"HTTP {res.status}"})
            return 1
        html, url = res.text, res.final_url
    page = extract(html, url)
    _print({"url": url or a.target, "types": page["jsonld_types"], "errors": page["jsonld_errors"],
            "microdata": page["has_microdata"],
            "objects": [{"type": o.get("@type"), "problems": [{"severity": s, "id": i, "message": m}
                                                             for s, i, m in check_object(o)]}
                        for o in page["jsonld"]],
            "jsonld": page["jsonld"] if a.full else None})
    return 0


def cmd_psi(a) -> int:
    from . import psi

    result = psi.run(a.url, a.strategy)
    _print(result)
    return 1 if result.get("error") else 0


def cmd_fetch(a) -> int:
    res = net.fetch(a.url, max_redirects=a.max_redirects)
    _print({"url": a.url, "final_url": res.final_url, "status": res.status, "error": res.error,
            "redirects": res.redirects, "elapsed_ms": res.elapsed_ms, "headers": res.headers,
            "bytes": len(res.body), "truncated": res.truncated})
    return 0 if res.ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run.py", description="Claude SEO Kit tools.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("audit", help="Crawl and audit a site")
    s.add_argument("url")
    s.add_argument("--max-pages", type=int, default=30)
    s.add_argument("--psi", action="store_true", help="Add PageSpeed Insights data for the home page")
    s.add_argument("--delay", type=float, default=0.2, help="Seconds between requests")
    s.add_argument("-o", "--output", help="Write JSON here and print a one-line summary")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("page", help="Everything about one page")
    s.add_argument("url")
    s.add_argument("--psi", action="store_true")
    s.add_argument("--text", action="store_true", help="Include the full visible text")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_page)

    s = sub.add_parser("robots", help="Parse robots.txt and show crawler access")
    s.add_argument("url")
    s.add_argument("--test", nargs="*", default=[], metavar="PATH", help="Paths to test for each crawler")
    s.set_defaults(func=cmd_robots)

    s = sub.add_parser("sitemap", help="Find, parse and spot-check sitemaps")
    s.add_argument("url", help="Site URL or a sitemap URL")
    s.add_argument("--check", type=int, default=10, help="Fetch this many listed URLs")
    s.add_argument("--max-urls", type=int, default=50000)
    s.add_argument("--list", metavar="FILE", help="Write every URL found, one per line")
    s.set_defaults(func=cmd_sitemap)

    s = sub.add_parser("schema", help="Validate structured data on a URL or local HTML file")
    s.add_argument("target")
    s.add_argument("--full", action="store_true", help="Include the parsed JSON-LD")
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser("psi", help="PageSpeed Insights: Core Web Vitals and lab score")
    s.add_argument("url")
    s.add_argument("--strategy", choices=("mobile", "desktop"), default="mobile")
    s.set_defaults(func=cmd_psi)

    s = sub.add_parser("fetch", help="Status, redirects and headers for a URL")
    s.add_argument("url")
    s.add_argument("--max-redirects", type=int, default=5)
    s.set_defaults(func=cmd_fetch)

    for name in TOOLS:
        sub.add_parser(name, help=f"{name} tool; see `run.py {name} -h`", add_help=False)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in TOOLS:
        import importlib

        module = importlib.import_module(f".{TOOLS[argv[0]]}", __package__)
        return module.main(argv[1:])
    args = build_parser().parse_args(argv)
    return args.func(args)
