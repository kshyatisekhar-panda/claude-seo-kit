"""PageSpeed Insights API: real-user Core Web Vitals (Chrome UX Report) and lab score.

Works without a key at low volume. Set PAGESPEED_API_KEY for regular use.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode

from . import net

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
FIELD_KEYS = {
    "LARGEST_CONTENTFUL_PAINT_MS": ("LCP", 1),
    "INTERACTION_TO_NEXT_PAINT": ("INP", 1),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": ("CLS", 0.01),  # reported as CLS x 100
}


def parse(data: dict, url: str) -> dict:
    out = {"url": url, "field": {}, "field_scope": None, "lab_score": None, "lab": {}}
    for scope_key, scope in (("loadingExperience", "page"), ("originLoadingExperience", "origin")):
        metrics = (data.get(scope_key) or {}).get("metrics") or {}
        found = {}
        for key, (name, factor) in FIELD_KEYS.items():
            p = (metrics.get(key) or {}).get("percentile")
            if p is not None:
                found[name] = p * factor
        if found:
            out["field"], out["field_scope"] = found, scope
            break
    lh = data.get("lighthouseResult") or {}
    score = ((lh.get("categories") or {}).get("performance") or {}).get("score")
    if score is not None:
        out["lab_score"] = round(score * 100)
    audits = lh.get("audits") or {}
    for key, name in (("largest-contentful-paint", "LCP"), ("cumulative-layout-shift", "CLS"),
                      ("total-blocking-time", "TBT")):
        value = (audits.get(key) or {}).get("numericValue")
        if value is not None:
            out["lab"][name] = round(value, 3)
    return out


def run(url: str, strategy: str = "mobile") -> dict:
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if os.environ.get("PAGESPEED_API_KEY"):
        params["key"] = os.environ["PAGESPEED_API_KEY"]
    res = net.fetch(f"{ENDPOINT}?{urlencode(params)}", timeout=120, max_bytes=30_000_000)
    if not res.ok:
        detail = res.error or f"HTTP {res.status}"
        if res.status == 429:
            detail = "rate limited; set PAGESPEED_API_KEY"
        return {"url": url, "error": f"PageSpeed Insights: {detail}"}
    try:
        return parse(json.loads(res.text), url)
    except json.JSONDecodeError:
        return {"url": url, "error": "PageSpeed Insights returned invalid JSON"}
