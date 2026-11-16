"""seokit/report.py: branded HTML report rendering."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from seokit import report as seo_report

DATA = {
    "site": "https://example.com",
    "date": "2026-11-16",
    "score": 82,
    "summary": "Good overall.",
    "categories": [{"name": "Technical", "score": 90}],
    "wins": ["Fast pages"],
    "findings": [
        {"title": "Low thing", "severity": "low", "fix": "Do it"},
        {"title": "Big thing", "severity": "critical", "detail": "Bad", "fix": "Fix it",
         "pages": [f"/p{i}" for i in range(12)]},
        {"title": "Odd severity", "severity": "urgent"},
    ],
}


def test_render_orders_and_counts():
    html = seo_report.render(json.loads(json.dumps(DATA)), brand_name="Acme")
    assert html.index("Big thing") < html.index("Odd severity") < html.index("Low thing")
    assert "1 critical" in html and "1 medium" in html and "1 low" in html
    assert "and 2 more" in html
    assert "<b>82</b>" in html and "Acme" in html


def test_everything_is_escaped():
    data = {"site": "https://x.com/<script>alert(1)</script>",
            "findings": [{"title": "<img src=x onerror=alert(1)>", "severity": "high"}]}
    html = seo_report.render(data)
    assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_bad_color_falls_back_and_score_optional():
    html = seo_report.render({"site": "s", "findings": []}, brand_color="red;}</style><script>")
    assert "</style><script>" not in html and "--brand: #D97757" in html
    assert "SEO health" not in html and "No issues found." in html


def test_validation_errors():
    with pytest.raises(ValueError):
        seo_report.render({"findings": []})
    with pytest.raises(ValueError):
        seo_report.render({"site": "x"})


def test_logo_rules(tmp_path):
    png = tmp_path / "logo.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert seo_report.logo_data_uri(str(png)).startswith("data:image/png;base64,")
    with pytest.raises(ValueError):
        seo_report.logo_data_uri(str(tmp_path / "logo.gif"))


def test_cli_writes_html(tmp_path, capsys):
    f = tmp_path / "f.json"
    f.write_text(json.dumps(DATA))
    out = tmp_path / "r.html"
    assert seo_report.main([str(f), "-o", str(out), "--brand-color", "#0F766E"]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert seo_report.main([str(tmp_path / "missing.json"), "-o", str(out)]) == 2
