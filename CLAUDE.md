# News Match

Browser game: each round is one news event covered by 3–4 outlets, and the player draws lines from
each article to the outlet that published it. Published with GitHub Pages from the root of `main`.

- `index.html` is the whole game (inline CSS and JS, no build, no dependencies). It loads only
  `rounds.json`, same-origin. Serve locally with `python3 -m http.server` from this folder (it
  can't fetch from `file://`).
- `fetch_news.py` writes `rounds.json`, using only the standard library. Browsers can't read most RSS
  feeds (no CORS), so nothing is fetched from the page. `--debug` prints each group, which is
  how to tune it. It refuses to overwrite `rounds.json` when fewer than `MIN_ROUNDS_TO_WRITE` rounds
  come out (exit 1), so a network outage never publishes an empty game.
- `rounds.json` is generated but committed, because Pages serves it.
  `.github/workflows/refresh.yml` regenerates it every 4 hours and commits it only when it changed.
- Outlets and their feeds are the `OUTLETS` list. Column 4 holds names masked as `[outlet]` in every
  article. Column 5 holds names masked only in the outlet's own articles, for ambiguous ones like
  "The Times". The page renders `[outlet]` as a chip.
- Grouping: TF-IDF over title (×2, plus title bigrams) and summary, then greedy average-linkage,
  best pairs first (`PAIR_MIN`, `LINK_MIN`). A group holds one article per outlet. A second article
  from an outlet already in a group is absorbed so it can't seed a near-duplicate round. Check
  changes with `--debug` against a live run: thresholds that are too low merge unrelated stories
  under broad words like "midterm".
- Places: `places.txt` maps place names, demonyms and big cities to a country, or to a US state,
  Canadian province or Australian state. Two sides merge only if `places_compatible`: they share a
  country, and where both name regions of it, at least one region. That keeps same-shaped stories
  apart (a Miami and an Everest helicopter crash, Guam vs San Diego rescues). An article naming no
  known place fits anything. Aliases are case-sensitive. Leave out names that are mostly
  something else (Jordan, Chad, Georgia), because a wrong place splits real stories. To test a
  change, run the old and new script on the same fetched feeds and diff the groups.
- Picking a round (`pick_articles`): at most `MAX_PER_ROUND` (4) articles. First the most central
  right-leaning and left-leaning ones (`LEAN`, broadly AllSides' and Ad Fontes Media's ratings;
  unlisted outlets count as centre), then random others, seeded by the group so an unchanged group
  gives the same round. Wire copy (`WIRE_OVERLAP`, the same AP headline at several outlets) is
  skipped. Rounds with both leanings sort first (`balance` in `rounds.json`), and the page plays
  the first unplayed rounds, so those are what players get.
- Round ids hash the round's URLs, so they're stable across refreshes that keep the same articles.
  The page stores played ids and lifetime stats in `localStorage` under `news-match:v1`. That
  origin is shared with every klaine.github.io page, so touch only this key.
- The results screen lists every story played (`game.played`, filled in `check()`): each
  article's headline, outlet, publish time and the player's guess, oldest first.
- Input: a drag starting on a dot draws a line (touch drags only from the dot, so a finger on a
  card still scrolls), and a click or tap selects one side and then the other. A click that ends a
  drag is suppressed. Lines are an SVG over the board, redrawn from the dots' positions by a
  `ResizeObserver`.
- Try a grouping change without overwriting `rounds.json`:
  `python3 fetch_news.py --out /tmp/x.json --debug`.
