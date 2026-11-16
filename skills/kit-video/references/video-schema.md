# Video Structured Data and Sitemaps

## VideoObject

Required by Google: `name`, `thumbnailUrl`, `uploadDate`.
Recommended: `description`, `duration` (ISO 8601), `contentUrl`, `embedUrl`,
`expires` if the video goes away, `interactionStatistic` for real view counts.

```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "How to make Swedish cinnamon buns",
  "description": "A step-by-step kanelbullar recipe, from dough to the knot.",
  "thumbnailUrl": ["https://example.com/thumbs/kanelbullar-16x9.jpg"],
  "uploadDate": "2026-10-04T08:00:00+02:00",
  "duration": "PT8M42S",
  "contentUrl": "https://example.com/video/kanelbullar.mp4",
  "embedUrl": "https://www.youtube.com/embed/VIDEO_ID"
}
```

- `uploadDate` needs a time zone. Use the real first publish date.
- `duration`: `PT8M42S` is 8 minutes 42 seconds.
- Thumbnails: at least 60 x 30 px; provide 16:9, and 4:3 and 1:1 if available.
- `contentUrl` points at the video file, `embedUrl` at the player. Give both
  when you can.

## Key moments

Either list clips yourself:

```json
"hasPart": [
  {"@type": "Clip", "name": "Making the dough", "startOffset": 30, "endOffset": 140,
   "url": "https://example.com/videos/kanelbullar?t=30"},
  {"@type": "Clip", "name": "Shaping the knots", "startOffset": 140, "endOffset": 330,
   "url": "https://example.com/videos/kanelbullar?t=140"}
]
```

or let Google find moments, if the page URL accepts a time parameter:

```json
"potentialAction": {
  "@type": "SeekToAction",
  "target": "https://example.com/videos/kanelbullar?t={seek_to_second_number}",
  "startOffset-input": "required name=seek_to_second_number"
}
```

Offsets are seconds from the start. Clip URLs must point to the same page with
a time parameter that really seeks.

## Live streams

Add `publication` with a `BroadcastEvent` (`isLiveBroadcast: true`,
`startDate`, `endDate`) to show a LIVE badge.

## Video sitemap

```xml
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">
  <url>
    <loc>https://example.com/videos/kanelbullar</loc>
    <video:video>
      <video:thumbnail_loc>https://example.com/thumbs/kanelbullar-16x9.jpg</video:thumbnail_loc>
      <video:title>How to make Swedish cinnamon buns</video:title>
      <video:description>A step-by-step kanelbullar recipe.</video:description>
      <video:content_loc>https://example.com/video/kanelbullar.mp4</video:content_loc>
      <video:duration>522</video:duration>
      <video:publication_date>2026-10-04T08:00:00+02:00</video:publication_date>
    </video:video>
  </url>
</urlset>
```

- `loc` is the watch page, not the video file.
- Give `content_loc` or `player_loc` (or both).
- `duration` is in seconds here, unlike schema.
- The sitemap can be a separate file listed in robots.txt or the sitemap index.

## Common failures

| Problem | Fix |
|---------|-----|
| "Video isn't on a watch page" in Search Console | Give the video its own page where it is the main content |
| "Video outside the viewport" | Place the player near the top, visible without scrolling |
| "Can't determine position" or "too small" | Player at least 140 px wide and visible in the rendered page |
| Thumbnail not found | Make the thumbnail URL public, stable and allowed in robots.txt |
