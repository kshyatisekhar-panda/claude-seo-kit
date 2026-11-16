# Changelog

## 2.0.0 (2026-11-16)

A complete rewrite. Claude SEO Kit is now built from scratch on its own
foundation.

- One Python package (`seokit`) behind a single entry point, `run.py`, with a
  private environment and four small dependencies.
- Safe fetching: every address is checked and connections are pinned to it.
- Site audit: crawler, robots.txt (RFC 9309) and sitemap parsing, 75 checks
  across technical, content, structured data, performance, AI search and
  local SEO, with scores per area.
- PageSpeed Insights integration for real-user Core Web Vitals.
- 16 skills behind `/seo-kit`: audit, page, technical, sitemap, schema,
  content, local, ai, fix, migrate, refresh, ci, report, logs and video.
- Reports can be built straight from an audit with `report --from-audit`.
