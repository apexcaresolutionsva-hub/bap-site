# buybap.com

Static site on GitHub Pages. **The homepage, `/features/`, `/leads/` and every county page are generated**; don't edit them by hand.

- `tools/build_site.py` builds `dist/` from live numbers (`site_stats()` in the BAP database), then the deploy workflow publishes `dist/`.
  It runs on every push and every morning (09:15 UTC), so counts, prices and plan limits never go stale.
- `data/features.json`: every tool BAP advertises, with an honest status label. Add a tool here when the app ships it.
- `data/counties.json`: which county pages exist. A county gets a page only when the database holds 300+ properties for it.
- `cash-offer/`, `funding/`, `post-a-deal/`, `text/`, `404.html`: hand-written pages. The build adds the shared head tags, colors and header.
- Test locally: `python tools/build_site.py --stats-file some_saved_stats.json`, then open `dist/`.

If the build can't fetch numbers or fails a sanity check (too few properties, missing plans, a leftover `{{placeholder}}`,
a forbidden phone number), the deploy is skipped and the live site keeps yesterday's version.
