# News Match

Same story, different newsroom. Each round shows one news event as covered by three to five
outlets, with the outlet names hidden. Draw a line from each article to the outlet that published it:
BBC News, Fox News, Al Jazeera, the Guardian, NPR, the Daily Mail, DW and more.

Each article's headline and summary come from that outlet's public RSS feed and link back to the
original.

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
(TF-IDF cosine over headline and summary). A group keeps at most one article per outlet, and
identical wire-service headlines are dropped, because no one could tell them apart. Groups with at
least three outlets become rounds.

A GitHub Action reruns it every four hours and commits `rounds.json` when it changed. GitHub Pages
serves `index.html` and `rounds.json` from the repository root.
