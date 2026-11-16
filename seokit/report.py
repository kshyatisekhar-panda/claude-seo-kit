#!/usr/bin/env python3
"""
Turn SEO audit findings into a branded, self-contained HTML report (and PDF).

Input is a findings JSON file the seo-report skill writes from audit output:

    {
      "site": "https://example.com",
      "date": "2026-11-16",
      "score": 82,
      "summary": "One paragraph for a non-technical reader.",
      "categories": [{"name": "Technical", "score": 90}],
      "findings": [{"title": "...", "severity": "critical|high|medium|low",
                    "category": "...", "detail": "...", "fix": "...",
                    "pages": ["/a", "/b"]}],
      "wins": ["Short positive notes"]
    }

Only "site" and "findings" are required. Every value is HTML-escaped. A logo
must be a local PNG, JPEG or SVG file and is embedded, so the report has no
external requests.

Usage:
    python run.py report findings.json -o report.html
    python run.py report findings.json -o report.html --pdf report.pdf \\
        --brand-name "Acme SEO" --brand-color "#0F766E" --logo logo.png --prepared-for "Client Ltd"
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path
from typing import Optional

SEVERITIES = ("critical", "high", "medium", "low")
SEV_COLORS = {"critical": "#B42318", "high": "#C4320A", "medium": "#B54708", "low": "#475467"}
LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def logo_data_uri(path: Optional[str]) -> str:
    if not path:
        return ""
    p = Path(path)
    mime = LOGO_TYPES.get(p.suffix.lower())
    if not mime:
        raise ValueError("logo must be .png, .jpg, .jpeg or .svg")
    if p.stat().st_size > 2_000_000:
        raise ValueError("logo is over 2 MB")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def score_color(score: float) -> str:
    return "#027A48" if score >= 80 else "#B54708" if score >= 50 else "#B42318"


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or not data.get("site"):
        raise ValueError("findings JSON needs a 'site'")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings JSON needs a 'findings' list")
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        f["severity"] = sev if sev in SEVERITIES else "medium"
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return data


def render(data: dict, brand_name: str = "SEO Report", brand_color: str = "#D97757",
           logo: str = "", prepared_for: str = "") -> str:
    data = validate(data)
    color = brand_color if _HEX.match(brand_color) else "#D97757"
    findings = data["findings"]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}

    score_html = ""
    if isinstance(data.get("score"), (int, float)):
        s = max(0, min(100, data["score"]))
        score_html = (f'<div class="score" style="--c:{score_color(s)}"><b>{int(s)}</b>'
                      f'<span>SEO health</span></div>')

    cats = "".join(
        f'<div class="cat"><div class="cat-top"><span>{e(c.get("name"))}</span>'
        f'<b>{int(c.get("score", 0))}</b></div><div class="bar"><i style="width:{max(0, min(100, int(c.get("score", 0))))}%;'
        f'background:{score_color(c.get("score", 0))}"></i></div></div>'
        for c in data.get("categories") or [] if isinstance(c, dict)
    )
    chips = "".join(
        f'<span class="chip" style="--c:{SEV_COLORS[s]}">{counts[s]} {s}</span>' for s in SEVERITIES
    )
    rows = []
    for i, f in enumerate(findings, 1):
        pages = f.get("pages") or []
        pages_html = ""
        if pages:
            shown = "".join(f"<li>{e(p)}</li>" for p in pages[:10])
            more = f"<li>and {len(pages) - 10} more</li>" if len(pages) > 10 else ""
            pages_html = f'<ul class="pages">{shown}{more}</ul>'
        rows.append(
            f'<section class="finding"><div class="f-head"><span class="sev" style="--c:{SEV_COLORS[f["severity"]]}">'
            f'{e(f["severity"])}</span><h3>{i}. {e(f.get("title"))}</h3>'
            f'<span class="f-cat">{e(f.get("category"))}</span></div>'
            + (f'<p>{e(f.get("detail"))}</p>' if f.get("detail") else "")
            + (f'<p class="fix"><b>Fix:</b> {e(f.get("fix"))}</p>' if f.get("fix") else "")
            + pages_html + "</section>"
        )
    wins = "".join(f"<li>{e(w)}</li>" for w in data.get("wins") or [])
    logo_html = f'<img class="logo" src="{e(logo)}" alt="">' if logo else ""
    prepared = f"<div>Prepared for <b>{e(prepared_for)}</b></div>" if prepared_for else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(brand_name)}: {e(data["site"])}</title>
<style>
:root {{ --brand: {color}; --ink: #101828; --muted: #475467; --line: #EAECF0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #F9FAFB; color: var(--ink);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
.page {{ max-width: 880px; margin: 0 auto; padding: 40px 24px 64px; }}
header {{ background: #fff; border-top: 6px solid var(--brand); border-radius: 12px; padding: 28px;
  display: flex; gap: 24px; align-items: center; justify-content: space-between;
  box-shadow: 0 1px 3px rgba(16,24,40,.08); }}
.logo {{ max-height: 44px; max-width: 180px; display: block; margin-bottom: 12px; }}
.brand {{ color: var(--brand); font-weight: 700; letter-spacing: .04em; text-transform: uppercase; font-size: 12px; }}
h1 {{ margin: 4px 0 6px; font-size: 26px; overflow-wrap: anywhere; }}
.meta {{ color: var(--muted); font-size: 13px; }}
.score {{ flex: none; width: 116px; height: 116px; border-radius: 50%; border: 9px solid var(--c);
  display: grid; place-content: center; text-align: center; }}
.score b {{ font-size: 34px; line-height: 1; }} .score span {{ font-size: 11px; color: var(--muted); }}
h2 {{ font-size: 18px; margin: 32px 0 12px; }}
.card {{ background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 20px; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
.chip {{ border: 1px solid var(--c); color: var(--c); border-radius: 999px; padding: 2px 10px; font-size: 13px; font-weight: 600; }}
.cats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
.cat-top {{ display: flex; justify-content: space-between; font-size: 14px; }}
.bar {{ height: 8px; background: var(--line); border-radius: 4px; margin-top: 6px; overflow: hidden; }}
.bar i {{ display: block; height: 100%; }}
.finding {{ background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 12px;
  break-inside: avoid; }}
.f-head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }}
.f-head h3 {{ margin: 0; font-size: 16px; flex: 1 1 300px; }}
.sev {{ background: var(--c); color: #fff; border-radius: 6px; padding: 1px 8px; font-size: 12px; font-weight: 700;
  text-transform: uppercase; }}
.f-cat {{ color: var(--muted); font-size: 13px; }}
.finding p {{ margin: 10px 0 0; }} .fix {{ background: #F9FAFB; border-left: 3px solid var(--brand); padding: 8px 12px; }}
.pages {{ margin: 10px 0 0; padding-left: 18px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
.wins li {{ margin: 4px 0; }}
footer {{ margin-top: 40px; color: var(--muted); font-size: 12px; text-align: center; }}
@media (max-width: 600px) {{ header {{ flex-direction: column; align-items: flex-start; }} }}
@media print {{ body {{ background: #fff; }} .page {{ padding: 0; }} header, .card, .finding {{ box-shadow: none; }} }}
</style></head>
<body><div class="page">
<header><div>{logo_html}<div class="brand">{e(brand_name)}</div>
<h1>{e(data["site"])}</h1>
<div class="meta">SEO audit{(" · " + e(data["date"])) if data.get("date") else ""}</div>{prepared}</div>{score_html}</header>
<h2>Summary</h2>
<div class="card">{f"<p style='margin:0'>{e(data['summary'])}</p>" if data.get("summary") else ""}
<div class="chips">{chips}</div></div>
{f'<h2>Scores by area</h2><div class="card cats">{cats}</div>' if cats else ""}
{f'<h2>What is working</h2><div class="card"><ul class="wins" style="margin:0">{wins}</ul></div>' if wins else ""}
<h2>Findings and fixes</h2>
{"".join(rows) or '<div class="card">No issues found.</div>'}
<footer>{e(brand_name)}</footer>
</div></body></html>
"""


AREA_NAMES = {"technical": "Technical", "content": "Content", "schema": "Structured data",
              "performance": "Performance", "ai": "AI search", "local": "Local"}


def from_audit(audit: dict, date: str = "") -> dict:
    """Convert `run.py audit --json` output into the findings shape render() takes."""
    from datetime import date as _date

    return {
        "site": audit.get("origin") or audit.get("url", ""),
        "date": date or _date.today().isoformat(),
        "score": audit.get("score"),
        "summary": audit.get("summary", ""),
        "categories": [{"name": AREA_NAMES.get(a, a.title()), "score": s}
                       for a, s in (audit.get("scores") or {}).items()],
        "wins": audit.get("wins", []),
        "findings": [{"title": f["title"], "severity": f["severity"],
                      "category": AREA_NAMES.get(f["area"], f["area"]),
                      "detail": f.get("detail", ""), "fix": f.get("fix", ""), "pages": f.get("pages", [])}
                     for f in audit.get("findings", []) if f.get("severity") != "info"],
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build a branded SEO report from findings JSON.")
    ap.add_argument("findings", help="Findings JSON file, or audit JSON with --from-audit")
    ap.add_argument("--from-audit", action="store_true", help="Input is `run.py audit --json` output")
    ap.add_argument("-o", "--output", required=True, help="HTML file to write")
    ap.add_argument("--pdf", help="Also write a PDF here (uses WeasyPrint)")
    ap.add_argument("--brand-name", default="SEO Report")
    ap.add_argument("--brand-color", default="#D97757", help="Hex color like #0F766E")
    ap.add_argument("--logo", help="Local PNG, JPEG or SVG logo")
    ap.add_argument("--prepared-for", default="")
    args = ap.parse_args(argv)
    try:
        data = json.loads(Path(args.findings).read_text(encoding="utf-8"))
        if args.from_audit:
            data = from_audit(data)
        page = render(data, args.brand_name, args.brand_color, logo_data_uri(args.logo), args.prepared_for)
    except (ValueError, OSError) as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 2
    Path(args.output).write_text(page, encoding="utf-8")
    print(f"report: wrote {args.output}")
    if args.pdf:
        try:
            from weasyprint import HTML
        except ImportError:
            print("report: WeasyPrint is not installed; run setup. HTML was written.", file=sys.stderr)
            return 1
        HTML(string=page).write_pdf(args.pdf)
        print(f"report: wrote {args.pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
