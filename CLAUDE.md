# News Match

Browser game: each round is one news event covered by 3–4 outlets, and the player draws lines from
each article to the outlet that published it. Published with GitHub Pages from the root of `main`,
at https://newsmatch.klaine.net/ (a CNAME record at NameSilo to `klaine.github.io`). The `CNAME`
file in the repo root holds that domain for Pages: keep it.

- `index.html` is the whole game (inline CSS and JS, no build, no dependencies). It loads only
  `rounds.json`, same-origin. Serve locally with `python3 -m http.server` from this folder (it
  can't fetch from `file://`).
- `404.html` sends any path that doesn't exist to `/` (Pages serves it for every 404, still with
  status 404). `python3 -m http.server` doesn't use it: open `/404.html` to try it locally.
- `fetch_news.py` writes `rounds.json`, using only the standard library. Browsers can't read most
  RSS feeds (no CORS), so nothing is fetched from the page. `--debug` prints each group, which is
  how to tune it. It refuses to overwrite `rounds.json` when fewer than `MIN_ROUNDS_TO_WRITE`
  rounds come out (exit 1), so a network outage never publishes an empty game.
- `rounds.json` is generated but committed, because Pages serves it.
  `.github/workflows/refresh.yml` regenerates it every three hours (at :17) and commits it when it
  changed, which is nearly every run because it records when it was built. It isn't more often
  because GitHub's schedules are best-effort and a skipped run costs its whole interval.
  The same run also commits `archive/` and `analysis/` (below). Its steps: fetch, analyse (can
  fail without stopping the commit), commit (rebased on the branch first, in case something landed
  meanwhile).
- Archive: after `rounds.json` is written, `write_archive` adds the run's standard and polarized
  rounds to `archive/YYYY-MM.json`, keyed by round id and filed under the month the story was first
  seen. A round seen again unchanged only gets `last_seen` updated. Round ids change whenever a
  group's articles change, so a round that shares an article with an archived round of the same
  kind is a new version of that story: it replaces the old entry, keeps its `first_seen`, and lists
  the replaced ids in `supersedes`. So the archive holds one entry per story, the latest version,
  and stays small enough for the analysis page to download whole. A failed fetch exits before
  this, so it never writes. `--no-archive` skips it for test runs.
- Bias analysis: `analyze_bias.py` sends archived rounds that have no entry in
  `analysis/YYYY-MM.json` to an AI model. Rounds on the page now come first, then newest first, at
  most 20 per scheduled run (a manual run can set `analysis_limit`). A round that has left the page
  is skipped when an id in its `supersedes` was analysed (an earlier version of the story is close
  enough); a round on the page is analysed as shown, so a live story that grows is analysed again.
  The provider is the repository variable `ANALYSIS_PROVIDER`: `opencode` (default, OpenCode Go at
  `https://opencode.ai/zen/go/v1`, secret `OPENCODE_API_KEY`, variable `OPENCODE_MODEL`) or
  `anthropic` (the Claude API, secret `ANTHROPIC_API_KEY`, variable `ANTHROPIC_MODEL`). With a key
  set but no model, the step lists the models that key can use and does nothing. Without the key
  the step does nothing. Each analysis has `bias_score` (0-100: how far apart the most and least
  loaded framings in the group are) and `score_reason` (a short text on the possible reasons). A
  reply that doesn't parse or lacks those fields is sent back once to correct; if it still fails,
  it is stored as an error and not retried: delete that entry to retry it. The game shows a
  story's analysis (`showFraming`, the `#framing` panel under the board) only once it is checked
  or skipped, because it names the outlets and would give the answers away. It loads
  `archive/index.json` and the newest two months' `analysis/` and `archive/` files once, a moment
  after the page loads, and like the analysis page falls back to an analysis made for an id in the
  round's `supersedes`.
- Analysis page: `analysis.html` shows the analyses on their own, for the current edition or any
  archived month, with sort and score-band filters. It isn't linked from the game page. It reads
  `rounds.json`, `archive/index.json` (the months, written by `write_archive` so the page can find
  them), `archive/YYYY-MM.json` and `analysis/YYYY-MM.json`. A round with no analysis of its own
  shows the one made for an id in its `supersedes`, tagged "earlier version analysed". Any
  `[outlet]` in the model's text is rendered as a chip, like in the game.
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
- `LEAN` scores each outlet from -3 (most left) to 3 (most right), broadly AllSides' and Ad Fontes
  Media's ratings; `side_of` reduces that to right, left, or centre (0; unlisted outlets).
- Picking a round (`pick_articles`): at most `MAX_PER_ROUND` (4) articles. First the most central
  right-leaning and left-leaning ones, then random others, seeded by the group so an unchanged group
  gives the same round. Wire copy (`WIRE_OVERLAP`, the same AP headline at several outlets) is
  skipped. Rounds with both leanings sort first (`balance` in `rounds.json`), and the page plays
  the first unplayed rounds, so those are what players get.
- Polarized rounds (`polarized_rounds`, the `polarized` list in `rounds.json`): each group with a
  right- and a left-leaning outlet gives one two-article round, from its most right-leaning and its
  most left-leaning outlet (ties go to the more central article; a same-wire pair moves on to the
  next pair). Most cohesive first. Standard mode plays only `rounds`, Polarized only `polarized`.
- Round ids hash the round's URLs, so they're stable across refreshes that keep the same articles.
  The page stores played ids, the chosen `mode`, and lifetime stats in `localStorage` under
  `news-match:v1`: `stats` for Standard, `polarStats` for Polarized. Ending a story also marks the
  other mode's round of the same story (one sharing an article) as played, so switching modes
  doesn't replay a story with its answers fresh in mind.
- Check and Skip both end a story in `endRound(skipped)`. Skip is for browsing: it replaces the
  lines with the right answers in the cards' own colours and names each card's outlet, but scores
  nothing (`game.results` gets `'skip'`, and `cur.skipped` keeps the lines out of green/red). It
  still marks the round as seen. A game of nothing but skips doesn't count in the lifetime stats.
- The results screen lists every story played (`game.played`, filled in `endRound()`): each
  article's headline, outlet, publish time and the player's guess, oldest first. Skipped stories
  say so and have no guesses.
- Save image (`renderStory`, `saveImage`) draws the current story on a canvas with its own fixed
  layout, so a phone gets lines too: the date, cards, outlets, the lines made so far and, once
  checked or skipped, the answers and the framing analysis (`layoutFraming`, `drawFraming`: as on the
  page, its list only when open), in the page's current light or dark colours (read from the CSS
  variables), 2400px wide. It's encoded as a JPEG synchronously, so on touch devices
  `navigator.share` still runs inside the tap and opens the share sheet. Elsewhere it downloads
  `news-match-<date>-story-<n>.jpg`. Keep the canvas look in step with the CSS when changing either.
- Input: a drag starting on a dot draws a line (touch drags only from the dot, so a finger on a
  card still scrolls), and a click or tap selects one side and then the other. A click that ends a
  drag is suppressed. Lines are an SVG over the board, redrawn from the dots' positions by a
  `ResizeObserver`.
- Phones (`narrow`, max-width 640px, the same breakpoint as the CSS): no lines or dragging, which
  were too cramped to follow. The outlets become a sticky bar above full-width cards, each card's
  `.slot` names its pick, and its colour fills the chosen outlet's dot. `.only-wide` and
  `.only-narrow` swap the instructions and labels that mention lines.
- Try a grouping change without overwriting `rounds.json` or the archive:
  `python3 fetch_news.py --out /tmp/x.json --debug --no-archive`.
