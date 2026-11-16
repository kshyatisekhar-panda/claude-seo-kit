#!/usr/bin/env python3
"""
Find pages that are losing search traffic and say why.

Compares two Search Console page reports (an earlier and a later period of
the same length) and labels each declining page with the most likely cause:

    ranking-loss   position got worse, so impressions and clicks fell
    ctr-loss       still shown as often, but fewer people click
    demand-drop    position held, but fewer people search for it
    dropped-out    page is missing from the later report entirely
    mixed          several signals moved at once

Inputs are CSV exports from the Search Console Performance report (Pages tab)
or JSON with rows of page, clicks, impressions, ctr and position.

Usage:
    python run.py decay --before q1.json --after q2.json
    python run.py decay --before before.csv --after after.csv --min-clicks 50 --json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

ACTIONS = {
    "ranking-loss": "Refresh the page: compare it with what ranks above it now, add what is "
                    "missing, update dates and facts, and add internal links from strong pages.",
    "ctr-loss": "Rewrite the title and meta description, check for new SERP features or an AI "
                "Overview taking the click, and add eligible structured data.",
    "demand-drop": "Check search demand (Google Trends, last year's same period). Usually "
                   "seasonal or a fading topic; do not rewrite a page that still ranks well.",
    "dropped-out": "Inspect the URL in Search Console: it may be noindexed, redirected, "
                   "canonicalised elsewhere, or returning an error.",
    "mixed": "Several signals moved. Check ranking queries for this page in Search Console "
             "before changing it.",
}


def _num(value) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace("%", "").replace(",", "").strip() or 0)


def load_report(path: str) -> dict[str, dict]:
    """Return {page: {clicks, impressions, ctr, position}} with ctr in percent."""
    text = Path(path).read_text(encoding="utf-8-sig")
    rows: list[dict] = []
    if text.lstrip().startswith("{") or text.lstrip().startswith("["):
        data = json.loads(text)
        raw = data.get("rows", []) if isinstance(data, dict) else data
        for r in raw:
            page = r.get("page") or (r.get("keys") or [None])[0]
            rows.append({"page": page, "clicks": r.get("clicks"), "impressions": r.get("impressions"),
                         "ctr": r.get("ctr"), "position": r.get("position")})
    else:
        reader = csv.DictReader(text.splitlines())
        for r in reader:
            low = {k.strip().lower(): v for k, v in r.items() if k}
            page = low.get("page") or low.get("top pages") or low.get("url")
            rows.append({"page": page, "clicks": low.get("clicks"), "impressions": low.get("impressions"),
                         "ctr": low.get("ctr"), "position": low.get("position")})
    out = {}
    for r in rows:
        if not r["page"]:
            continue
        clicks, impr = _num(r["clicks"]), _num(r["impressions"])
        ctr = _num(r["ctr"]) if r["ctr"] not in (None, "") else (clicks / impr * 100 if impr else 0)
        out[r["page"]] = {"clicks": clicks, "impressions": impr, "ctr": ctr, "position": _num(r["position"])}
    return out


def _pct(before: float, after: float) -> Optional[float]:
    return round((after - before) / before * 100, 1) if before else None


def diagnose(b: dict, a: Optional[dict]) -> str:
    if a is None:
        return "dropped-out"
    impr_change = (a["impressions"] - b["impressions"]) / b["impressions"] if b["impressions"] else 0
    pos_change = a["position"] - b["position"]  # positive means worse
    ctr_change = (a["ctr"] - b["ctr"]) / b["ctr"] if b["ctr"] else 0
    if pos_change >= 2 or (b["position"] and pos_change / b["position"] >= 0.3):
        return "ranking-loss"
    if abs(impr_change) < 0.2 and ctr_change <= -0.2:
        return "ctr-loss"
    if impr_change <= -0.2 and pos_change < 1:
        return "demand-drop"
    return "mixed"


def analyse(before: dict[str, dict], after: dict[str, dict], min_clicks: float = 20,
            drop: float = 0.2) -> dict:
    decaying = []
    for page, b in before.items():
        if b["clicks"] < min_clicks:
            continue
        a = after.get(page)
        a_clicks = a["clicks"] if a else 0.0
        if a_clicks > b["clicks"] * (1 - drop):
            continue
        cause = diagnose(b, a)
        decaying.append({
            "page": page,
            "cause": cause,
            "clicks_before": int(b["clicks"]),
            "clicks_after": int(a_clicks),
            "clicks_lost": int(b["clicks"] - a_clicks),
            "clicks_change_pct": _pct(b["clicks"], a_clicks),
            "impressions_change_pct": _pct(b["impressions"], a["impressions"]) if a else -100.0,
            "position_before": round(b["position"], 1),
            "position_after": round(a["position"], 1) if a else None,
            "ctr_before": round(b["ctr"], 2),
            "ctr_after": round(a["ctr"], 2) if a else None,
            "action": ACTIONS[cause],
        })
    decaying.sort(key=lambda r: r["clicks_lost"], reverse=True)
    totals = {k: sum(1 for d in decaying if d["cause"] == k) for k in ACTIONS}
    total_b = sum(p["clicks"] for p in before.values())
    total_a = sum(p["clicks"] for p in after.values())
    return {
        "site_clicks_before": int(total_b),
        "site_clicks_after": int(total_a),
        "site_clicks_change_pct": _pct(total_b, total_a),
        "pages_compared": len(before),
        "decaying_pages": len(decaying),
        "clicks_lost_on_decaying": sum(d["clicks_lost"] for d in decaying),
        "by_cause": totals,
        "pages": decaying,
    }


def render_text(report: dict, limit: int) -> str:
    lines = [
        f"Site clicks: {report['site_clicks_before']} -> {report['site_clicks_after']} "
        f"({report['site_clicks_change_pct']}%)",
        f"{report['decaying_pages']} decaying pages, {report['clicks_lost_on_decaying']} clicks lost. "
        + ", ".join(f"{k}: {v}" for k, v in report["by_cause"].items() if v),
        "",
    ]
    for d in report["pages"][:limit]:
        pos = f"pos {d['position_before']} -> {d['position_after']}" if d["position_after"] else "gone"
        lines.append(f"-{d['clicks_lost']:>6}  {d['cause']:<13} {pos:<18} {d['page']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Detect content decay between two GSC periods.")
    ap.add_argument("--before", required=True, help="Earlier period: Search Console CSV or JSON")
    ap.add_argument("--after", required=True, help="Later period, same length")
    ap.add_argument("--min-clicks", type=float, default=20, help="Ignore pages below this many clicks before")
    ap.add_argument("--drop", type=float, default=0.2, help="Minimum click loss as a fraction (0.2 = 20%%)")
    ap.add_argument("--limit", type=int, default=30, help="Rows in the text table")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = analyse(load_report(args.before), load_report(args.after), args.min_clicks, args.drop)
    print(json.dumps(report, indent=2) if args.json else render_text(report, args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
