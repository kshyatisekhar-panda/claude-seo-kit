# Astro SEO Fix Patterns

For Astro 4 and 5. Read `astro.config.*` and the main layout first.

## The site origin

Canonicals and the sitemap need `site`:

```js
// astro.config.mjs
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://example.com",
  integrations: [sitemap()],
});
```

`@astrojs/sitemap` writes `sitemap-index.xml`. Add it with
`npx astro add sitemap` so the dependency is installed too.

## One SEO component in the layout

Most Astro sites have a `BaseLayout.astro` or `Layout.astro`. Give it SEO props
and render the head there once:

```astro
---
// src/layouts/BaseLayout.astro
interface Props { title: string; description: string; image?: string; noindex?: boolean }
const { title, description, image = "/og.png", noindex = false } = Astro.props;
const canonical = new URL(Astro.url.pathname, Astro.site);
const ogImage = new URL(image, Astro.site);
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{`${title} | Brand`}</title>
    <meta name="description" content={description} />
    <link rel="canonical" href={canonical} />
    {noindex && <meta name="robots" content="noindex, follow" />}
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:image" content={ogImage} />
    <meta property="og:url" content={canonical} />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="sitemap" href="/sitemap-index.xml" />
    <slot name="head" />
  </head>
  <body><slot /></body>
</html>
```

Then each page passes real values:
`<BaseLayout title={post.data.title} description={post.data.description}>`.
For content collections, add `title` and `description` to the collection
schema so a missing value fails the build.

## robots.txt

Static: `public/robots.txt`. Dynamic, so the sitemap URL follows `site`:

```ts
// src/pages/robots.txt.ts
import type { APIRoute } from "astro";

export const GET: APIRoute = ({ site }) =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${new URL("sitemap-index.xml", site)}\n`);
```

## JSON-LD

`set:html` with `JSON.stringify`, escaping `<`:

```astro
<script type="application/ld+json"
  set:html={JSON.stringify(schema).replace(/</g, "\\u003c")} />
```

Pass it into the layout's `head` slot: `<Fragment slot="head">...</Fragment>`.

## Images

`<Image />` from `astro:assets` requires `alt`; use `alt=""` for decorative
images. For the hero image set `loading="eager"` and `fetchpriority="high"`.

## Multilingual

With Astro i18n routing, render hreflang links in the layout for every locale
plus `x-default`, using `getRelativeLocaleUrl` from `astro:i18n`, and set
`<html lang={Astro.currentLocale}>`.

## Redirects

`redirects` in astro.config for a few routes. For a large map in static mode,
use the host's redirect file (see the kit-migrate skill).

## Verify

`npm run build`, then `run.py ci --dir dist --base-url https://example.com`.
