"""Findings and scoring.

A finding is one problem (or one confirmed strength) with a stable id. The
same rule firing on many pages is one finding with a page list, which keeps
reports readable and scores fair: a site is not punished forty times for one
template bug.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")
PENALTY = {"critical": 30, "high": 14, "medium": 6, "low": 2, "info": 0}
AREAS = ("technical", "content", "schema", "performance", "ai", "local")
AREA_WEIGHT = {"technical": 0.28, "content": 0.24, "schema": 0.14, "performance": 0.14,
               "ai": 0.10, "local": 0.10}


@dataclass
class Finding:
    id: str
    area: str
    severity: str
    title: str
    detail: str = ""
    fix: str = ""
    pages: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Collector:
    """Merges repeated findings by id and keeps the page list."""

    def __init__(self) -> None:
        self._by_id: dict[str, Finding] = {}

    def add(self, f: Finding, page: str = "") -> None:
        existing = self._by_id.get(f.id)
        if existing is None:
            self._by_id[f.id] = f
            existing = f
        if page and page not in existing.pages:
            existing.pages.append(page)

    def all(self) -> list[Finding]:
        return sorted(self._by_id.values(),
                      key=lambda f: (SEVERITY_ORDER.index(f.severity), f.area, f.id))


def area_scores(findings: list[Finding], pages_checked: int, areas: list[str]) -> dict[str, int]:
    """100 minus penalties. A rule hitting more pages costs more, with diminishing returns."""
    scores = {}
    for area in areas:
        penalty = 0.0
        for f in findings:
            if f.area != area:
                continue
            spread = len(f.pages) / pages_checked if pages_checked and f.pages else 1.0
            penalty += PENALTY[f.severity] * (0.6 + 0.4 * math.sqrt(min(spread, 1.0)))
        scores[area] = max(0, round(100 - penalty))
    return scores


def overall_score(scores: dict[str, int]) -> int:
    weights = {a: AREA_WEIGHT[a] for a in scores}
    total = sum(weights.values())
    return round(sum(scores[a] * w for a, w in weights.items()) / total) if total else 0
