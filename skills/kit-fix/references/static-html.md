# Static HTML SEO Fix Patterns

For hand-written HTML sites or exports from tools without an SEO API. Every
page carries its own head, so check for a shared include or template first
(Eleventy, Hugo and Jekyll partials, PHP includes) and edit that instead.

## Head template

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Page topic first | Brand</title>
  <meta name="description" content="What the reader gets from this page, about 120 to 155 characters.">
  <link rel="canonical" href="https://example.com/page/">
  <meta property="og:title" content="Page topic first">
  <meta property="og:description" content="Same promise as the meta description.">
  <meta property="og:image" content="https://example.com/og/page.png">
  <meta property="og:url" content="https://example.com/page/">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
</head>
```

- Canonical and `og:url` are absolute and match the URL the server answers on,
  including the trailing slash convention.
- A page that must stay out of search: `<meta name="robots" content="noindex, follow">`.

## hreflang

In every language version, list all versions including itself:

```html
<link rel="alternate" hreflang="en" href="https://example.com/en/page/">
<link rel="alternate" hreflang="sv" href="https://example.com/sv/page/">
<link rel="alternate" hreflang="x-default" href="https://example.com/en/page/">
```

## JSON-LD

```html
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization",
 "name": "Brand", "url": "https://example.com/", "logo": "https://example.com/logo.png"}
</script>
```

Validate it parses before saving. Put site-wide types on the home page only.

## sitemap.xml and robots.txt

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc><lastmod>2026-11-01</lastmod></url>
</urlset>
```

```
User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml
```

List only canonical, indexable 200 URLs. Use real modification dates.

## Images

Every `<img>` has `alt`; decorative images use `alt=""`. Add `width` and
`height` to stop layout shift, and `loading="lazy"` on images below the fold
only, never on the main hero image.
