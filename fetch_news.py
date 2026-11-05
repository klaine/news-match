#!/usr/bin/env python3
"""Fetch news feeds, group articles about the same event, write rounds.json.

Usage: python3 fetch_news.py [--out rounds.json] [--hours 48] [--debug]

Standard library only. Each outlet's RSS/Atom feeds are fetched in parallel, cleaned (HTML
stripped, outlet names masked so they can't give the answer away), and grouped by TF-IDF cosine
similarity of title + summary. A group keeps at most one article per outlet; groups with at
least MIN_OUTLETS outlets become game rounds. If too few rounds come out (feeds down, network
gone), the existing rounds.json is left untouched and the script exits with status 1.
"""

import argparse
import concurrent.futures as cf
import email.utils
import hashlib
import html
import json
import math
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# id, display name, feeds, aliases masked in every article, aliases masked only in its own.
OUTLETS = [
    ("bbc", "BBC News", [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/rss.xml",
    ], ["BBC News", "BBC"], []),
    ("guardian", "The Guardian", [
        "https://www.theguardian.com/world/rss",
        "https://www.theguardian.com/us-news/rss",
        "https://www.theguardian.com/uk-news/rss",
    ], ["The Guardian", "Guardian"], ["Observer"]),
    ("npr", "NPR", [
        "https://feeds.npr.org/1001/rss.xml",
        "https://feeds.npr.org/1004/rss.xml",
        "https://feeds.npr.org/1014/rss.xml",
    ], ["NPR"], []),
    ("aljazeera", "Al Jazeera", [
        "https://www.aljazeera.com/xml/rss/all.xml",
    ], ["Al Jazeera"], []),
    ("fox", "Fox News", [
        "https://moxie.foxnews.com/google-publisher/latest.xml",
        "https://moxie.foxnews.com/google-publisher/world.xml",
        "https://moxie.foxnews.com/google-publisher/politics.xml",
        "https://moxie.foxnews.com/google-publisher/us.xml",
    ], ["Fox News Digital", "Fox News", "FOX News", "Fox Business", "Fox & Friends"], []),
    ("sky", "Sky News", [
        "https://feeds.skynews.com/feeds/rss/home.xml",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://feeds.skynews.com/feeds/rss/us.xml",
        "https://feeds.skynews.com/feeds/rss/politics.xml",
    ], ["Sky News"], []),
    ("dw", "DW", [
        "https://rss.dw.com/xml/rss-en-all",
    ], ["Deutsche Welle", "DW"], []),
    ("nyt", "The New York Times", [
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    ], ["The New York Times", "New York Times", "NYT"], ["The Times"]),
    ("cbs", "CBS News", [
        "https://www.cbsnews.com/latest/rss/main",
        "https://www.cbsnews.com/latest/rss/world",
        "https://www.cbsnews.com/latest/rss/politics",
    ], ["CBS News", "CBS"], []),
    ("nbc", "NBC News", [
        "https://feeds.nbcnews.com/nbcnews/public/news",
        "https://feeds.nbcnews.com/nbcnews/public/world",
        "https://feeds.nbcnews.com/nbcnews/public/politics",
    ], ["NBC News", "NBC"], []),
    ("abc", "ABC News", [
        "https://abcnews.go.com/abcnews/topstories",
        "https://abcnews.go.com/abcnews/internationalheadlines",
        "https://abcnews.go.com/abcnews/politicsheadlines",
    ], ["ABC News"], []),
    ("france24", "France 24", [
        "https://www.france24.com/en/rss",
    ], ["France 24", "FRANCE 24"], []),
    ("euronews", "Euronews", [
        "https://www.euronews.com/rss",
    ], ["Euronews", "euronews"], []),
    ("cbc", "CBC News", [
        "https://www.cbc.ca/webfeed/rss/rss-topstories",
        "https://www.cbc.ca/webfeed/rss/rss-world",
    ], ["CBC News", "CBC"], []),
    ("nypost", "New York Post", [
        "https://nypost.com/news/feed/",
        "https://nypost.com/us-news/feed/",
        "https://nypost.com/politics/feed/",
    ], ["New York Post", "NY Post"], ["The Post", "the Post"]),
    ("dailymail", "Daily Mail", [
        "https://www.dailymail.co.uk/news/index.rss",
        "https://www.dailymail.co.uk/news/worldnews/index.rss",
    ], ["Daily Mail", "DailyMail", "MailOnline", "Mail Online"], []),
    ("breitbart", "Breitbart", [
        "https://feeds.feedburner.com/breitbart",
    ], ["Breitbart News", "Breitbart"], []),
    ("wsj", "The Wall Street Journal", [
        "https://feeds.content.dowjones.io/public/rss/RSSWorldNews",
        "https://feeds.content.dowjones.io/public/rss/RSSUSnews",
    ], ["The Wall Street Journal", "Wall Street Journal", "WSJ"], ["The Journal"]),
    ("latimes", "Los Angeles Times", [
        "https://www.latimes.com/world-nation/rss2.0.xml",
        "https://www.latimes.com/politics/rss2.0.xml",
    ], ["Los Angeles Times", "L.A. Times", "LA Times"], ["The Times"]),
    ("scmp", "South China Morning Post", [
        "https://www.scmp.com/rss/91/feed",
        "https://www.scmp.com/rss/2/feed",
    ], ["South China Morning Post", "SCMP"], ["the Post"]),
]

USER_AGENT = "Mozilla/5.0 (compatible; news-match/1.0)"
MASK = "[outlet]"
SUMMARY_MAX = 300       # characters shown per summary
MIN_OUTLETS = 3         # a round needs at least this many outlets
MAX_PER_ROUND = 5       # and shows at most this many
MAX_ROUNDS = 24
MIN_ROUNDS_TO_WRITE = 3
PAIR_MIN = 0.24         # cosine similarity that starts or joins a group (best pair first)
LINK_MIN = 0.17         # mean similarity a newcomer needs with every member of the group
WIRE_OVERLAP = 0.7      # title word overlap (Jaccard) above which two articles count as one

STOP = set("""
a about above across after afterwards again against ago ahead all almost alone along already also
although always am amid among an and another any anyone anything are around as at away back be
became because become been before behind being below beside besides between beyond both but by
can cannot could did do does doing done down during each either else enough even ever every few
first for former from further get gets getting give given go goes going gone got had has have
having he her here hers herself him himself his how however i if in inside into is it its itself
just last latest least less like live made make makes many may me might more most mostly much must
my near nearly need new news next no nor not now of off often on once one only onto or other others
our ours out over own past per perhaps put rather really said same say saying says see seen she
should since so some something still such take taken than that the their theirs them then there
these they thing things this those though three through thus to today told too toward towards two
under until up update updates upon us very via want was watch way we week weeks well were what when
where whether which while who whom whose why will with within without would year years yet you your
video videos report reports reported according amid time times day days people latest breaking
""".split())


# ---------------------------------------------------------------- fetching and parsing

def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(item, *names):
    for name in names:
        for c in item:
            if local(c.tag) == name and (c.text or "").strip():
                return c.text.strip()
    return ""


def child_link(item):
    for c in item:
        if local(c.tag) == "link":
            href = c.get("href")
            if href and c.get("rel", "alternate") == "alternate":
                return href.strip()
            if (c.text or "").strip():
                return c.text.strip()
    guid = child_text(item, "guid")
    return guid if guid.startswith("http") else ""


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse_feed(data):
    root = ET.fromstring(data)
    for item in root.iter():
        if local(item.tag) not in ("item", "entry"):
            continue
        yield {
            "title": child_text(item, "title"),
            "summary": child_text(item, "description", "summary", "encoded", "content"),
            "url": child_link(item),
            "published": parse_date(child_text(item, "pubDate", "published", "updated", "date")),
        }


# ---------------------------------------------------------------- cleaning

TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
INVISIBLE = re.compile(r"[​-‏⁠﻿]")
SUMMARY_TAIL = [
    re.compile(r"\s*Continue reading\.*\s*$", re.I),
    re.compile(r"\s*The post .{0,300}? appeared first on .{0,80}$", re.I),
    re.compile(r"\s*(Read|Click here)( the)? (more|full (story|article)).{0,40}$", re.I),
    re.compile(r"\s*\[(…|\.\.\.)\]\s*$"),
]
LIVE_HEAD = re.compile(r"^(?:live(?: updates?| blog)?|breaking)\s*[:|–—-]\s*", re.I)
LIVE_TAIL = re.compile(r"\s*[–—-]\s*(?:live(?: updates?)?|as it happened|latest updates?)\s*$", re.I)


BLOCK = re.compile(r"</?(?:p|br|li|h\d|div|blockquote)\b[^>]*>", re.I)
ASIDE = re.compile(r"<(ul|ol|figure|table|aside)\b.*?</\1>", re.I | re.S)  # related links, images


def clean_text(s):
    s = html.unescape(TAG.sub(" ", html.unescape(s or "")))
    s = SPACE.sub(" ", INVISIBLE.sub("", s)).strip()
    return re.sub(r" ([,.;:!?])(?=\s|$)", r"\1", s)  # "midterms , which" where a link was


def clean_summary(s):
    """Paragraphs become sentences: a standfirst often has no full stop of its own."""
    s = ASIDE.sub(" ", html.unescape(s or ""))
    out = []
    for part in BLOCK.split(s):
        part = clean_text(part)
        if not part:
            continue
        if out and not re.search(r"[.!?…:;\"”’']$", out[-1]):
            out[-1] += "."
        out.append(part)
    s = " ".join(out)
    for pat in SUMMARY_TAIL:
        s = pat.sub("", s)
    return s


def alias_pattern(aliases):
    alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    return re.compile(rf"(?<![\w.])(?:{alts})(?!\w)")


def truncate(s, n):
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:–—- ")
    return cut + "…"


def clean_article(raw, outlet, global_pat, self_pats):
    title = clean_text(raw["title"])
    summary = clean_summary(raw["summary"])
    title = LIVE_TAIL.sub("", LIVE_HEAD.sub("", title))
    # "Headline - BBC News", "Headline | DW": drop the outlet suffix rather than mask it.
    title = re.sub(rf"\s*[|–—-]\s*{global_pat.pattern}\s*$", "", title)
    if summary.lower().startswith(title.lower()):
        summary = summary[len(title):].lstrip(" .:–—-")
    def mask(text):
        text = global_pat.sub(MASK, text)
        return self_pats[outlet].sub(MASK, text) if outlet in self_pats else text
    return mask(title), truncate(mask(summary), SUMMARY_MAX)


# ---------------------------------------------------------------- similarity

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokens(text):
    text = unicodedata.normalize("NFKD", text.replace("’", "'").replace("[outlet]", " "))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    out = []
    for w in WORD.findall(text):
        w = w.split("'")[0]
        if len(w) < 2 or w in STOP or (w.isdigit() and len(w) != 4):
            continue
        out.append(stem(w))
    return out


def vectors(articles):
    bags = []
    for a in articles:
        t = tokens(a["title"])
        bag = Counter()
        for w in t:
            bag[w] += 2.0
        for w1, w2 in zip(t, t[1:]):
            bag[w1 + " " + w2] += 1.5
        for w in tokens(a["summary"]):
            bag[w] += 1.0
        bags.append(bag)
    df = Counter(term for bag in bags for term in bag)
    n = len(bags)
    vecs = []
    for bag in bags:
        v = {t: (1 + math.log(c)) * math.log((n + 1) / (df[t] + 1)) for t, c in bag.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items() if x > 0})
    return vecs


def similarities(vecs, outlets):
    postings = defaultdict(list)
    for i, v in enumerate(vecs):
        for t, x in v.items():
            postings[t].append((i, x))
    sims = defaultdict(float)
    for plist in postings.values():
        if len(plist) > 0.2 * len(vecs):
            continue
        for a in range(len(plist)):
            i, xi = plist[a]
            for b in range(a + 1, len(plist)):
                j, xj = plist[b]
                if outlets[i] != outlets[j]:
                    sims[(i, j)] += xi * xj
    return sims


def cluster(articles, sims):
    """Greedy average-linkage grouping, best pairs first, one article per outlet per group."""
    def sim(i, j):
        return sims.get((i, j) if i < j else (j, i), 0.0)

    def link(a, b):
        return sum(sim(i, j) for i in a for j in b) / (len(a) * len(b))

    group_of, groups, next_id = {}, {}, 0
    for (i, j), s in sorted(sims.items(), key=lambda kv: -kv[1]):
        if s < PAIR_MIN:
            break
        gi, gj = group_of.get(i), group_of.get(j)
        if (gi is not None and gi == gj) or gi == -1 or gj == -1:
            continue  # already together, or an absorbed duplicate
        a = groups[gi] if gi is not None else {i}
        b = groups[gj] if gj is not None else {j}
        if link(a, b) < LINK_MIN:
            continue
        if {articles[k]["outlet"] for k in a} & {articles[k]["outlet"] for k in b}:
            # Same story, but this outlet is already in the group. Absorb a lone article so it
            # can't seed a near-duplicate round of its own.
            if gi is not None and gj is None:
                group_of[j] = -1
            elif gj is not None and gi is None:
                group_of[i] = -1
            continue
        if gi is None and gj is None:
            gid, next_id = next_id, next_id + 1
            groups[gid] = set()
        elif gi is None or (gj is not None and len(groups[gj]) > len(groups[gi])):
            gid = gj
        else:
            gid = gi
        merged = a | b
        for g in (gi, gj):
            if g is not None and g != gid:
                del groups[g]
        groups[gid] = merged
        for k in merged:
            group_of[k] = gid
    return [sorted(g) for g in groups.values()], sim


def rounds_from(articles, groups, sim, vecs):
    rounds = []
    for g in groups:
        if len(g) < MIN_OUTLETS:
            continue
        centrality = {i: sum(sim(i, j) for j in g if j != i) / (len(g) - 1) for i in g}
        keep, kept_words = [], []
        for i in sorted(g, key=lambda i: -centrality[i]):
            # Wire copy (the same AP/Reuters headline at several outlets) can't be told apart.
            words = set(tokens(articles[i]["title"]))
            if any(len(words & w) / (len(words | w) or 1) >= WIRE_OVERLAP for w in kept_words):
                continue
            keep.append(i)
            kept_words.append(words)
        keep = keep[:MAX_PER_ROUND]
        if len(keep) < MIN_OUTLETS:
            continue
        pairs = [(i, j) for x, i in enumerate(keep) for j in keep[x + 1:]]
        cohesion = sum(sim(i, j) for i, j in pairs) / len(pairs)
        topic = Counter()
        for i in keep:
            topic.update({t: x for t, x in vecs[i].items() if " " not in t})
        rid = hashlib.sha1("\n".join(sorted(articles[i]["url"] for i in keep)).encode()).hexdigest()[:10]
        rounds.append({
            "id": rid,
            "topic": [t for t, _ in topic.most_common(4)],
            "cohesion": round(cohesion, 3),
            "articles": [{k: articles[i][k] for k in ("outlet", "title", "summary", "url", "published")}
                         for i in keep],
        })
    rounds.sort(key=lambda r: (-len(r["articles"]), -r["cohesion"]))
    return rounds[:MAX_ROUNDS]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "rounds.json"))
    ap.add_argument("--hours", type=float, default=48, help="ignore articles older than this")
    ap.add_argument("--debug", action="store_true", help="print the groups and near misses")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)
    global_pat = alias_pattern([a for o in OUTLETS for a in o[3]])
    self_pats = {o[0]: alias_pattern(o[4]) for o in OUTLETS if o[4]}

    jobs = [(o[0], url) for o in OUTLETS for url in o[2]]
    with cf.ThreadPoolExecutor(12) as ex:
        results = list(ex.map(lambda job: (job, _try_fetch(job[1])), jobs))

    articles, seen, ok_outlets = [], set(), set()
    for (outlet, url), (data, err) in results:
        if err:
            print(f"  ! {outlet}: {url}: {err}", file=sys.stderr)
            continue
        try:
            items = list(parse_feed(data))
        except ET.ParseError as e:
            print(f"  ! {outlet}: {url}: {e}", file=sys.stderr)
            continue
        ok_outlets.add(outlet)
        for raw in items:
            if raw["published"] and not (cutoff <= raw["published"] <= now + timedelta(hours=2)):
                continue
            title, summary = clean_article(raw, outlet, global_pat, self_pats)
            if not raw["url"] or len(title.split()) < 4:
                continue
            key_url = re.sub(r"^https?://(www\.)?|[?#].*$", "", raw["url"])
            key_title = (outlet, re.sub(r"\W+", "", title.lower()))
            if key_url in seen or key_title in seen:
                continue
            seen.update((key_url, key_title))
            articles.append({
                "outlet": outlet, "title": title, "summary": summary, "url": raw["url"],
                "published": (raw["published"] or now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    print(f"{len(articles)} articles from {len(ok_outlets)}/{len(OUTLETS)} outlets", file=sys.stderr)
    vecs = vectors(articles)
    groups, sim = cluster(articles, similarities(vecs, [a["outlet"] for a in articles]))
    rounds = rounds_from(articles, groups, sim, vecs)
    print(f"{len(rounds)} rounds ({sum(len(r['articles']) for r in rounds)} articles)", file=sys.stderr)

    if args.debug:
        for r in rounds:
            print(f"\n== {' '.join(r['topic'])}  cohesion {r['cohesion']}", file=sys.stderr)
            for a in r["articles"]:
                print(f"   {a['outlet']:10s} {a['title'][:100]}", file=sys.stderr)

    if len(rounds) < MIN_ROUNDS_TO_WRITE:
        print(f"only {len(rounds)} rounds; keeping the existing {args.out}", file=sys.stderr)
        return 1

    used = {a["outlet"] for r in rounds for a in r["articles"]}
    doc = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outlets": {o[0]: {"name": o[1]} for o in OUTLETS if o[0] in used},
        "rounds": rounds,
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, args.out)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


def _try_fetch(url):
    try:
        return fetch(url), None
    except Exception as e:  # one dead feed mustn't stop the rest
        return None, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    sys.exit(main())
