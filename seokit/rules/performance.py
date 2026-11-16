"""Performance rules from PageSpeed Insights data (Core Web Vitals) and page markup."""

from __future__ import annotations

from ..findings import Finding

# Google's Core Web Vitals thresholds at the 75th percentile: (good up to, poor above)
THRESHOLDS = {
    "LCP": (2500, 4000, "ms", "Largest Contentful Paint"),
    "INP": (200, 500, "ms", "Interaction to Next Paint"),
    "CLS": (0.1, 0.25, "", "Cumulative Layout Shift"),
}
FIXES = {
    "LCP": "Serve the hero image early (no lazy loading, fetchpriority=high, modern format, right "
           "size), cut render-blocking CSS and JavaScript, and speed up the server response.",
    "INP": "Break up long JavaScript tasks, load third-party scripts later, and keep event handlers "
           "small.",
    "CLS": "Give images, embeds and ads fixed width and height, and avoid inserting content above "
           "what is already shown.",
}


def rate(metric: str, value: float) -> str:
    good, poor, _, _ = THRESHOLDS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs-improvement"


def site_rules(site: dict, add) -> None:
    psi = site.get("psi")
    pages = site["pages"]
    if pages:
        home = pages[0]
        hero_lazy = [i for i in home["images"][:3] if i["loading"] == "lazy"]
        if hero_lazy:
            add(Finding("perf-hero-lazy", "performance", "medium", "Top images are lazy-loaded",
                        detail="Lazy loading the first visible image delays Largest Contentful Paint.",
                        fix="Remove loading=lazy from above-the-fold images and add fetchpriority=high "
                            "to the main one."), page=home["url"])
        unsized = [i for p in pages for i in p["images"] if i["src"] and not (i["width"] and i["height"])]
        if len(unsized) >= 5:
            add(Finding("perf-img-no-size", "performance", "low", "Images without width and height",
                        detail=f"{len(unsized)} images, which can shift the layout as they load.",
                        fix="Set width and height (or CSS aspect-ratio) on every image."))
    if not psi:
        return
    if psi.get("error"):
        add(Finding("perf-psi-error", "performance", "info", "PageSpeed Insights unavailable",
                    detail=psi["error"]))
        return
    field_data = psi.get("field") or {}
    if not field_data:
        add(Finding("perf-no-field-data", "performance", "info", "No real-user speed data yet",
                    detail="Chrome UX Report has too little traffic for this page, so only lab "
                           "numbers are available.",
                    fix="Use the lab numbers as a guide; field data appears once traffic grows."))
    for metric, value in field_data.items():
        if metric not in THRESHOLDS:
            continue
        verdict = rate(metric, value)
        if verdict == "good":
            continue
        good, poor, unit, name = THRESHOLDS[metric]
        shown = f"{value:.2f}" if metric == "CLS" else f"{int(value)} {unit}"
        add(Finding(f"cwv-{metric.lower()}", "performance",
                    "high" if verdict == "poor" else "medium",
                    f"{name} is {verdict.replace('-', ' ')}",
                    detail=f"{shown} at the 75th percentile of real visits (good is {good}{unit or ''} "
                           f"or less).", fix=FIXES[metric]), page=psi.get("url", ""))
    score = psi.get("lab_score")
    if score is not None and score < 50:
        add(Finding("perf-lab-score", "performance", "medium", "Low Lighthouse performance score",
                    detail=f"{score}/100 on mobile in the lab test.",
                    fix="Start with the largest opportunities in the PageSpeed report."))
