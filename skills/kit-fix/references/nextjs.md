# Next.js SEO Fix Patterns

For Next.js 13.4+ App Router (current: Next.js 15 and 16) and the Pages Router.
Read the project's `next.config.*` and root layout first.

## App Router: Metadata API

Set shared values once in the root layout. `metadataBase` makes every relative
URL in metadata absolute, including canonicals and Open Graph images.

```tsx
// app/layout.tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  metadataBase: new URL("https://example.com"),
  title: { default: "Brand", template: "%s | Brand" },
  description: "What the site offers, in one sentence.",
  openGraph: { siteName: "Brand", type: "website" },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
```

For a localized `app/[locale]/layout.tsx`, set `lang={locale}` on `<html>`.

Per page, static or dynamic:

```tsx
// app/blog/[slug]/page.tsx
export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> },
): Promise<Metadata> {
  const { slug } = await params;          // params is a Promise in Next.js 15+
  const post = await getPost(slug);
  return {
    title: post.title,                     // the layout template adds the brand
    description: post.excerpt,
    alternates: { canonical: `/blog/${slug}` },
    openGraph: { title: post.title, description: post.excerpt, images: [post.image] },
  };
}
```

- `alternates.canonical` per page; never one canonical in the layout for all.
- Multilingual: `alternates.languages: { en: "/en/x", sv: "/sv/x", "x-default": "/en/x" }`.
  Every language version must list all versions, itself included.
- `robots: { index: false, follow: true }` for pages that must stay out.
- Do not also hand-write `<title>` or `<meta>` in the JSX; that duplicates tags.

## Sitemap and robots

```ts
// app/sitemap.ts
import type { MetadataRoute } from "next";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await getPosts();
  return [
    { url: "https://example.com/", lastModified: new Date() },
    ...posts.map((p) => ({ url: `https://example.com/blog/${p.slug}`, lastModified: p.updatedAt })),
  ];
}
```

```ts
// app/robots.ts
import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/"] }],
    sitemap: "https://example.com/sitemap.xml",
  };
}
```

Use real `lastModified` dates from content, not `new Date()` for every URL.
Large sites: `generateSitemaps` splits into several files. Remove any static
`public/sitemap.xml` or `public/robots.txt` that would conflict.

## JSON-LD

Render in the page component. Escape `<` so content cannot close the script tag:

```tsx
const jsonLd = { "@context": "https://schema.org", "@type": "Article", headline: post.title };

<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
/>
```

Organization or WebSite schema goes in the root layout once.

## Images

`next/image` requires `alt`. Use `alt=""` for decorative images. Give the LCP
image `priority` (Next.js 15) or `preload` (Next.js 16) so it is not lazy-loaded.

## Redirects

Permanent moves go in `next.config.*` `redirects()` with `permanent: true`
(308). Generate large maps with the kit-migrate skill.

## Pages Router

```tsx
import Head from "next/head";

<Head>
  <title>{`${post.title} | Brand`}</title>
  <meta name="description" content={post.excerpt} />
  <link rel="canonical" href={`https://example.com/blog/${post.slug}`} />
</Head>
```

Set `lang` in `pages/_document.tsx` on `<Html lang="en">`, or through `i18n`
in next.config. Sitemaps: `pages/sitemap.xml.ts` with `getServerSideProps`, or
the `next-sitemap` package if the project already uses it.

## Static export

With `output: "export"`, run `run.py ci --dir out`. `sitemap.ts` and
`robots.ts` still work; redirects in next.config do not, so put them in the
host's config (Vercel, Netlify, nginx).
