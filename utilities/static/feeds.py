"""Sitemap, robots.txt, and Atom feed XML — crawler-facing static content."""

SITEMAP_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://pilgri.ms/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://pilgri.ms/about</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://pilgri.ms/lore</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://pilgri.ms/crew</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>
  <url><loc>https://pilgri.ms/expeditions</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>
  <url><loc>https://pilgri.ms/depot</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>
  <url><loc>https://pilgri.ms/colony</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>
  <url><loc>https://pilgri.ms/inventory</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>
  <url><loc>https://pilgri.ms/changelog</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>
</urlset>'''

ROBOTS_TXT = (
    'User-agent: *\n'
    'Allow: /\n'
    'Sitemap: https://pilgri.ms/sitemap.xml\n'
    'Feed: https://pilgri.ms/feed.xml\n'
)

ATOM_FEED_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Pilgrims</title>
  <subtitle>A Mars colony strategy game that respects your time. Changelog and updates.</subtitle>
  <link href="https://pilgri.ms/"/>
  <link href="https://pilgri.ms/feed.xml" rel="self"/>
  <id>https://pilgri.ms/</id>
  <updated>2026-02-07T08:50:00Z</updated>
  <entry>
    <title>v2.1 — Depot &amp; QoL Improvements</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v2.1</id>
    <updated>2026-02-07T08:50:00Z</updated>
    <summary>Richer Depot upgrade cards with full effect stats, smarter ARIA intelligence across Research/Colony/HQ/Depot pages, and 15+ bug fixes across the colony.</summary>
  </entry>
  <entry>
    <title>v2.0.3 — Signal &amp; Expeditions</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v2.0.3</id>
    <updated>2026-02-06T00:00:00Z</updated>
    <summary>New Signal origin sites, expedition haul improvements, and crew mission balancing.</summary>
  </entry>
  <entry>
    <title>v2.0.2 — EVA Suit &amp; ARIA Improvements</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v2.0.2</id>
    <updated>2026-02-05T00:00:00Z</updated>
    <summary>Simplified EVA suit system and expanded ARIA contextual awareness.</summary>
  </entry>
  <entry>
    <title>v2.0.1 — Depot Full-Stack Redesign</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v2.0.1</id>
    <updated>2026-02-04T00:00:00Z</updated>
    <summary>Complete Depot redesign with new card layout, build queue, and upgrade paths.</summary>
  </entry>
  <entry>
    <title>v2.0 — Economy Redesign</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v2.0</id>
    <updated>2026-02-03T00:00:00Z</updated>
    <summary>Major economy overhaul: new currency system, rebalanced costs, and sustainable progression loop.</summary>
  </entry>
  <entry>
    <title>v1.5 — Codebase Refactor</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v1.5</id>
    <updated>2026-01-15T00:00:00Z</updated>
    <summary>Architecture cleanup and codebase refactor for long-term maintainability.</summary>
  </entry>
  <entry>
    <title>v1.0 — Initial Launch</title>
    <link href="https://pilgri.ms/changelog"/>
    <id>https://pilgri.ms/changelog#v1.0</id>
    <updated>2025-10-01T00:00:00Z</updated>
    <summary>First public release of Pilgrims: Mars colony character creation, expeditions, and base building.</summary>
  </entry>
</feed>'''
