#!/usr/bin/env python3
"""Ask an AI model what the headlines and summaries of each archived story show about framing.
Results go to analysis/YYYY-MM.json, keyed by round id.

Usage: ANALYSIS_PROVIDER=opencode OPENCODE_API_KEY=... OPENCODE_MODEL=... python3 analyze_bias.py [--limit 6]

Providers (ANALYSIS_PROVIDER, default "opencode"):
  opencode   OpenCode Go, OPENCODE_API_KEY and OPENCODE_MODEL
  anthropic  the Claude API, ANTHROPIC_API_KEY and ANTHROPIC_MODEL
Optional base URL overrides: OPENCODE_BASE_URL, ANTHROPIC_BASE_URL.

Standard library only. Only rounds without an analysis are sent: the ones in the current
rounds.json first, then the newest archived. At most --limit per run, so the hourly refresh stays
inside the plan's quota. Without a key it does nothing; without a model it lists the models the key
can use and does nothing. Both exit 0, so the refresh is never blocked by this step.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "news-match/1.0"
RETRY_DELAYS = (2, 4, 8, 16)  # seconds, for rate limits and server errors
RETRYABLE = (429, 500, 502, 503, 504, 529)

PROVIDERS = {
    "opencode": {
        "base": "https://opencode.ai/zen/go/v1",
        "base_env": "OPENCODE_BASE_URL",
        "key_env": "OPENCODE_API_KEY",
        "model_env": "OPENCODE_MODEL",
    },
    "anthropic": {
        "base": "https://api.anthropic.com/v1",
        "base_env": "ANTHROPIC_BASE_URL",
        "key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
    },
}

SYSTEM = """You compare how news outlets frame the same event. You are given several articles
(headline and summary each) about one story, each labelled with its outlet. "[outlet]" marks a
place where an outlet named itself; ignore it.

Use only the text you are given. Look for differences in word choice, emphasis, what is left out,
who is quoted, and loaded labels. Quote the words you rely on. Do not guess at motives, and do not
call an outlet biased overall: say what the text shows and how strongly. If the articles may not
be about the same event, say so.

Reply with only one JSON object, no other text, in this shape:
{"same_event": true or false,
 "shared_facts": ["facts all the articles agree on"],
 "differences": [{"outlet": "outlet label", "kind": "word choice | emphasis | omission | sourcing | loaded label | other",
                  "observation": "what differs and why it matters", "quote": "the words used"}],
 "possible_bias": "none apparent | slight | notable | unclear",
 "summary": "one or two sentences"}"""


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def archived_rounds(archive_dir):
    """Every archived round as (round id, month, entry), newest first."""
    out = []
    if os.path.isdir(archive_dir):
        for name in os.listdir(archive_dir):
            if re.fullmatch(r"\d{4}-\d{2}\.json", name):
                doc = read_json(os.path.join(archive_dir, name), {"rounds": {}})
                out += [(rid, doc["month"], entry) for rid, entry in doc["rounds"].items()]
    out.sort(key=lambda x: x[2]["first_seen"], reverse=True)
    return out


def analysed_ids(analysis_dir):
    done = set()
    if os.path.isdir(analysis_dir):
        for name in os.listdir(analysis_dir):
            if re.fullmatch(r"\d{4}-\d{2}\.json", name):
                done.update(read_json(os.path.join(analysis_dir, name), {"analyses": {}})["analyses"])
    return done


def prompt_for(entry):
    lines = []
    for n, a in enumerate(entry["articles"], 1):
        lines.append(f"Article {n} (outlet: {a['outlet']}, published {a['published']})")
        lines.append(f"Headline: {a['title']}")
        if a.get("summary"):
            lines.append(f"Summary: {a['summary']}")
        lines.append("")
    return "\n".join(lines).strip()


def headers_for(provider, key, session):
    if provider == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    # OpenCode Go wants a session per conversation; one per run is enough.
    return {"Authorization": f"Bearer {key}", "x-opencode-session": session}


def call(base, headers, path, body=None, method="POST"):
    """One request, retried on rate limits and server errors. Raises urllib.error.HTTPError or
    URLError when it gives up."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        **headers, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    for delay in (*RETRY_DELAYS, None):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE or delay is None:
                raise
        except urllib.error.URLError:
            if delay is None:
                raise
        time.sleep(delay)


def list_models(provider, base, headers):
    return [m["id"] for m in call(base, headers, "/models", method="GET").get("data", [])]


def ask(provider, base, headers, model, prompt):
    """The model's reply as text."""
    if provider == "anthropic":
        reply = call(base, headers, "/messages", {
            # No temperature: some Claude models reject it.
            "model": model, "max_tokens": 1024, "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        })
        return "".join(b.get("text", "") for b in reply["content"] if b.get("type") == "text")
    reply = call(base, headers, "/chat/completions", {
        "model": model, "temperature": 0.2,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    })
    return reply["choices"][0]["message"]["content"]


def parse_reply(text):
    """The model's JSON object, even if it wrapped it in prose or a code fence."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--limit", type=int, default=6, help="most rounds to analyse in one run")
    ap.add_argument("--archive-dir", default=os.path.join(BASE_DIR, "archive"))
    ap.add_argument("--analysis-dir", default=os.path.join(BASE_DIR, "analysis"))
    ap.add_argument("--rounds", default=os.path.join(BASE_DIR, "rounds.json"))
    args = ap.parse_args()

    provider = os.environ.get("ANALYSIS_PROVIDER", "").strip() or "opencode"
    if provider not in PROVIDERS:
        print(f"unknown ANALYSIS_PROVIDER {provider!r}; use one of: {', '.join(PROVIDERS)}", file=sys.stderr)
        return 1
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "").strip()
    model = os.environ.get(cfg["model_env"], "").strip()
    base = os.environ.get(cfg["base_env"], cfg["base"]).rstrip("/")
    if not key:
        print(f"{cfg['key_env']} is not set; skipping the bias analysis ({provider}).")
        return 0

    headers = headers_for(provider, key, str(uuid.uuid4()))
    if not model:
        try:
            models = list_models(provider, base, headers)
        except (urllib.error.URLError, ValueError) as e:
            print(f"{cfg['model_env']} is not set, and listing models failed: {e}")
            return 0
        print(f"{cfg['model_env']} is not set. Models this key can use ({provider}):")
        print("\n".join(f"  {m}" for m in models) or "  (none listed)")
        return 0

    # Rounds on the page now come first, then the rest of the archive, newest first.
    live = read_json(args.rounds, {"rounds": [], "polarized": []})
    live_ids = [r["id"] for r in live.get("rounds", []) + live.get("polarized", [])]
    archive = {rid: (month, entry) for rid, month, entry in archived_rounds(args.archive_dir)}
    order = [rid for rid in live_ids if rid in archive] + [rid for rid in archive if rid not in live_ids]
    done = analysed_ids(args.analysis_dir)
    todo = [rid for rid in order if rid not in done][: args.limit]
    if not todo:
        print("nothing new to analyse")
        return 0
    print(f"analysing {len(todo)} round(s) with {provider} / {model}")

    for rid in todo:
        month, entry = archive[rid]
        path = os.path.join(args.analysis_dir, f"{month}.json")
        doc = read_json(path, {"month": month, "analyses": {}})
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            text = ask(provider, base, headers, model, prompt_for(entry))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"request failed: HTTP {e.code} {detail}", file=sys.stderr)
            if e.code == 404:
                print(f"the model may not exist; check {cfg['model_env']} against the list it prints "
                      f"when unset", file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"request failed: {e.reason}", file=sys.stderr)
            return 1
        except (KeyError, IndexError, TypeError) as e:
            print(f"unexpected reply shape from {provider}: {e!r}", file=sys.stderr)
            return 1
        result = parse_reply(text)
        base_record = {"provider": provider, "model": model, "analysed_at": stamp}
        if result is None:
            record = {**base_record, "error": "reply was not a JSON object", "raw": text[:1000]}
        else:
            record = {**base_record, "result": result}
        doc["analyses"][rid] = record
        write_json(path, doc)  # save each one, so a failure later keeps the earlier work
        print(f"  {rid}: {'ok' if result is not None else 'unparseable reply'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
