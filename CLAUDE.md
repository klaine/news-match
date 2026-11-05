# News Match

Browser game: each round is one news event covered by 3–5 outlets, and the player draws lines from
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
  from an outlet already in a group is absorbed so it can't seed a near-duplicate round, and wire
  copy (`WIRE_OVERLAP`, the same AP headline at several outlets) is dropped from a round. Check
  changes with `--debug` against a live run: thresholds that are too low merge unrelated stories
  under broad words like "midterm".
- Round ids hash the round's URLs, so they're stable across refreshes that keep the same articles.
  The page stores played ids and lifetime stats in `localStorage` under `news-match:v1`. That
  origin is shared with every klaine.github.io page, so touch only this key.
- Input: a drag starting on a dot draws a line (touch drags only from the dot, so a finger on a
  card still scrolls), and a click or tap selects one side and then the other. A click that ends a
  drag is suppressed. Lines are an SVG over the board, redrawn from the dots' positions by a
  `ResizeObserver`.
- Try a grouping change without overwriting `rounds.json`:
  `python3 fetch_news.py --out /tmp/x.json --debug`.
