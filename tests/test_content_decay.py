"""seokit/decay.py: decay detection and cause labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from seokit import decay as cd


def row(page, clicks, impressions, position, ctr=None):
    ctr = ctr if ctr is not None else round(clicks / impressions * 100, 2)
    return {"page": page, "clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position}


BEFORE = {"rows": [
    row("/ranking", 200, 4000, 3.0),
    row("/ctr", 200, 4000, 3.0),
    row("/demand", 200, 4000, 3.0),
    row("/gone", 100, 2000, 5.0),
    row("/stable", 200, 4000, 3.0),
    row("/tiny", 5, 100, 8.0),
]}
AFTER = {"rows": [
    row("/ranking", 80, 2500, 7.5),
    row("/ctr", 100, 4100, 3.1),
    row("/demand", 110, 2200, 3.2),
    row("/stable", 190, 3900, 3.0),
    row("/tiny", 0, 50, 15.0),
]}


def load(tmp_path):
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(BEFORE))
    a.write_text(json.dumps(AFTER))
    return cd.load_report(str(b)), cd.load_report(str(a))


def test_causes(tmp_path):
    report = cd.analyse(*load(tmp_path))
    causes = {p["page"]: p["cause"] for p in report["pages"]}
    assert causes == {"/ranking": "ranking-loss", "/ctr": "ctr-loss", "/demand": "demand-drop",
                      "/gone": "dropped-out"}
    assert report["pages"][0]["page"] == "/ranking"  # most clicks lost first
    assert report["by_cause"]["ctr-loss"] == 1


def test_min_clicks_filters_small_pages(tmp_path):
    report = cd.analyse(*load(tmp_path), min_clicks=1)
    assert "/tiny" in {p["page"] for p in report["pages"]}


def test_gsc_ui_csv_export(tmp_path):
    csv_text = "Top pages,Clicks,Impressions,CTR,Position\nhttps://ex.com/a,1,200,\"0.5%\",4.2\n"
    f = tmp_path / "p.csv"
    f.write_text("﻿" + csv_text, encoding="utf-8")
    data = cd.load_report(str(f))
    assert data["https://ex.com/a"] == {"clicks": 1.0, "impressions": 200.0, "ctr": 0.5, "position": 4.2}


def test_keys_only_rows(tmp_path):
    f = tmp_path / "k.json"
    f.write_text(json.dumps({"rows": [{"keys": ["/k"], "clicks": 3, "impressions": 30, "ctr": 10.0, "position": 2}]}))
    assert "/k" in cd.load_report(str(f))


def test_cli_text(tmp_path, capsys):
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(BEFORE))
    a.write_text(json.dumps(AFTER))
    assert cd.main(["--before", str(b), "--after", str(a)]) == 0
    out = capsys.readouterr().out
    assert "4 decaying pages" in out and "ranking-loss" in out
