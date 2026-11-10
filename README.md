# News Match

Same story, different newsroom. Each round shows one news event as covered by three or four
outlets, with the outlet names hidden. Draw a line from each article to the outlet that published
it: BBC News, Fox News, Al Jazeera, the Guardian, NPR, the Daily Mail, DW and more. Skip a story to
see who wrote what without scoring it, and save any story, lines and answers included, as an image.

Each article's headline and summary come from that outlet's public RSS feed and link back to the
original.

Play it at https://newsmatch.klaine.net/.

## Run it locally

```sh
python3 fetch_news.py          # fetch the feeds and write rounds.json
python3 -m http.server 8418    # then open http://localhost:8418
```

`fetch_news.py --debug` prints how the articles were grouped. It uses only Python 3's standard
library.

## How it works

`fetch_news.py` reads about 45 feeds from 20 outlets, strips the HTML, and hides each outlet's name
wherever it appears in the text. It then groups articles from the last 48 hours by word similarity
(TF-IDF cosine over headline and summary), at most one article per outlet. Articles set in
different places don't group, even when the words match: `places.txt` lists the countries, US
states and cities it knows. Groups with at least
three outlets become rounds of up to four articles. Each round tries to include one outlet commonly
rated right-leaning (Fox News, Breitbart, New York Post, Daily Mail) and one rated left-leaning
(the Guardian, NPR, the New York Times, CBS, NBC, ABC, the LA Times); the other picks are random.
Rounds that have both come first. Groups with a right- and a left-leaning outlet also give a
Polarized round of just two articles, from the most right-leaning and the most left-leaning outlet
covering the story. Identical wire-service headlines are dropped, because no one could
tell them apart.

A GitHub Action reruns it hourly (when GitHub runs the schedule) and commits `rounds.json` when it changed. Each run
also adds its groups to a monthly archive in `archive/`, one entry per story. When an AI provider
key (OpenCode Go or the Claude API) is set as a repository secret, it also asks an AI model about
the framing in new groups and stores the answers in `analysis/`. GitHub Pages serves `index.html`
and `rounds.json` from the repository root.
