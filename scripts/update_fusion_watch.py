#!/usr/bin/env python3
"""
Fusion Watch Auto-Updater
==========================
Weekly automation: ingests RSS feeds → Claude analysis → updates data.json
dynamic section only. The locked section (confidence, barriers, COI) is
never read by this script and never written.

Usage:
  python update_fusion_watch.py [--data PATH] [--dry-run]

Required env var:
  ANTHROPIC_API_KEY

Optional env vars:
  ANTHROPIC_MODEL     — default: claude-opus-4-5
  MAX_FEED_ITEMS      — max RSS items per company (default: 6)
"""

import os
import re
import sys
import json
import argparse
import textwrap
import datetime

import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic

DATA_FILE      = os.getenv("FW_DATA_PATH", "data.json")
MODEL          = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
MAX_FEED_ITEMS = int(os.getenv("MAX_FEED_ITEMS", "6"))

COMPANIES = [
    {
        "id": "kstar",
        "name": "KSTAR",
        "context": (
            "KSTAR is the South Korean government tokamak at KAERI/KFE. "
            "Track: plasma confinement records (temperature, duration), "
            "new experimental results, government funding changes."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=KSTAR+fusion+plasma+Korea&hl=en-US&gl=US&ceid=US:en",
            "https://feeds.reuters.com/reuters/scienceNews",
        ],
        "keywords": ["kstar", "korean fusion", "korea institute", "plasma record", "kaeri"],
    },
    {
        "id": "cfs",
        "name": "Commonwealth Fusion Systems",
        "context": (
            "CFS is building SPARC using high-temp superconducting magnets (20 tesla). "
            "Track: SPARC construction progress, magnet test results, funding rounds, "
            "timeline updates for first plasma, Google and Breakthrough Energy partnerships."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=Commonwealth+Fusion+Systems+SPARC&hl=en-US&gl=US&ceid=US:en",
            "https://feeds.reuters.com/reuters/scienceNews",
        ],
        "keywords": ["commonwealth fusion", "cfs", "sparc", "superconducting magnet"],
    },
    {
        "id": "helion",
        "name": "Helion Energy",
        "context": (
            "Helion is pursuing Field Reversed Configuration fusion with Polaris (Gen 7). "
            "Track: Polaris operational milestones, Microsoft PPA status, "
            "funding updates, first power target 2028."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=Helion+Energy+fusion+Polaris&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=Helion+Microsoft+power+purchase&hl=en-US&gl=US&ceid=US:en",
        ],
        "keywords": ["helion", "polaris fusion", "helion energy", "microsoft fusion", "field reversed"],
    },
    {
        "id": "tae",
        "name": "TAE Technologies / TMTG",
        "context": (
            "TAE announced H-boron fusion at commercially relevant ratios Jan 2026 "
            "and is merging with Trump Media in a $6B all-stock deal targeting mid-2026. "
            "Track: SEC S-4 filing status, merger regulatory approval, Trump Jr board role, "
            "H-boron technical updates, DJT stock movements."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=TAE+Technologies+Trump+Media+merger&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=TAE+fusion+TMTG+SEC+merger&hl=en-US&gl=US&ceid=US:en",
        ],
        "keywords": ["tae technologies", "tae fusion", "tmtg merger", "trump media fusion", "h-boron"],
    },
    {
        "id": "iter",
        "name": "ITER",
        "context": (
            "ITER is the 35-nation international tokamak in Cadarache, France. "
            "Track: construction progress, budget changes (>$22B), "
            "first plasma timeline (targeting 2027), tritium breeding blanket validation."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=ITER+fusion+reactor+2026&hl=en-US&gl=US&ceid=US:en",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        ],
        "keywords": ["iter", "cadarache", "international thermonuclear", "iter organization"],
    },
    {
        "id": "east",
        "name": "EAST / China Program",
        "context": (
            "China's EAST tokamak in Hefei, backed by $1.5B under China's 14th Five-Year Plan. "
            "Track: EAST experimental records, China fusion budget announcements, "
            "comparison to KSTAR, CAEA program updates."
        ),
        "feeds": [
            "https://news.google.com/rss/search?q=EAST+China+fusion+reactor+plasma&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=China+fusion+energy+CAEA+2026&hl=en-US&gl=US&ceid=US:en",
        ],
        "keywords": ["east tokamak", "china fusion", "caea", "hefei fusion", "chinese fusion"],
    },
]

GLOBAL_FEEDS = [
    "https://news.google.com/rss/search?q=nuclear+fusion+energy+milestone+2026&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fusion+energy+commercial+breakthrough&hl=en-US&gl=US&ceid=US:en",
]

SYSTEM_PROMPT = (
    "You are an intelligence analyst updating a fusion energy tracking dashboard. "
    "Be concise, precise, and evidence-based. "
    "Output ONLY valid JSON with the exact schema provided. "
    "Never add markdown code fences or extra text outside the JSON."
)

STATUS_OPTIONS = {
    "active":  ["On Track", "Record Set", "Ahead of Schedule", "Milestone Achieved", "Advancing"],
    "deal":    ["Merger Pending", "Under Review", "Deal Active", "Regulatory Review"],
    "watch":   ["Delayed", "Tracking", "Monitoring", "Behind Schedule", "Stalled"],
    "alert":   ["At Risk", "Setback", "Funding Gap", "Critical Issue"],
}


def fetch_feed_items(company):
    items    = []
    keywords = [k.lower() for k in company["keywords"]]
    for feed_url in company["feeds"]:
        try:
            r    = requests.get(feed_url, timeout=12, headers={"User-Agent": "Mozilla/5.0 FusionWatchBot/1.0"})
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:20]:
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                if any(kw in (title + " " + summary).lower() for kw in keywords):
                    items.append({
                        "title":   title,
                        "summary": BeautifulSoup(summary, "html.parser").get_text()[:350],
                        "date":    entry.get("published", entry.get("updated", "")),
                        "source":  feed.feed.get("title", feed_url),
                    })
        except Exception as exc:
            print(f"  [WARN] {feed_url}: {exc}", file=sys.stderr)
    seen, unique = set(), []
    for item in items:
        key = item["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:MAX_FEED_ITEMS]


def fetch_global_items():
    items = []
    for url in GLOBAL_FEEDS:
        try:
            r    = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 FusionWatchBot/1.0"})
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:10]:
                items.append({"title": entry.get("title", ""), "date": entry.get("published", ""), "source": feed.feed.get("title", url)})
        except Exception as exc:
            print(f"  [WARN] {url}: {exc}", file=sys.stderr)
    return items[:10]


def analyze_company(client, company, current_data, feed_items, today):
    items_text = "\n".join(
        f"[{i+1}] {it['date']} | {it['source']}\n    {it['title']}\n    {it['summary']}"
        for i, it in enumerate(feed_items)
    ) or "(No new RSS items — use training knowledge for latest status.)"

    prompt = textwrap.dedent(f"""
        Today is {today}. Updating Fusion Watch entry for "{company['name']}".

        CONTEXT: {company['context']}

        CURRENT DATA:
        {json.dumps(current_data, indent=2)}

        RECENT FEED ({len(feed_items)} items):
        {items_text}

        Return JSON with exactly these keys:
        {{
          "flag": "<active | deal | watch | alert>",
          "status_label": "<short label from STATUS OPTIONS>",
          "status_class": "<same value as flag>",
          "description": "<2 sentences max — present tense, factual>",
          "metrics": [
            {{"val": "<value>", "key": "<UPPERCASE LABEL>"}},
            {{"val": "<value>", "key": "<UPPERCASE LABEL>"}},
            {{"val": "<value>", "key": "<UPPERCASE LABEL>"}}
          ],
          "last_updated": "{today}"
        }}

        STATUS OPTIONS: {json.dumps(STATUS_OPTIONS)}
        Keep metrics at exactly 3 items. Return ONLY JSON.
    """).strip()

    msg = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM_PROMPT,
                                  messages=[{"role": "user", "content": prompt}])
    raw = re.sub(r"^```(?:json)?\s*", "", msg.content[0].text.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  [WARN] JSON parse failed for {company['id']}: {exc}", file=sys.stderr)
        return {}


def analyze_banner(client, company_results, global_items, today):
    summaries = [f"[{cid.upper()}] {r.get('status_label','')} — {r.get('description','')[:150]}"
                 for cid, r in company_results.items() if r]
    global_text = "\n".join(f"  {it['date']} | {it['title']}" for it in global_items[:8]) or "(none)"

    prompt = textwrap.dedent(f"""
        Today is {today}.
        Company summaries:
        {chr(10).join(summaries)}

        Global headlines:
        {global_text}

        Return JSON:
        {{
          "text": "<banner sentence — factual, specific, cite date if possible>",
          "highlight": "<key phrase to bold>",
          "last_updated": "{today}"
        }}
        Return ONLY JSON.
    """).strip()

    msg = client.messages.create(model=MODEL, max_tokens=300, system=SYSTEM_PROMPT,
                                  messages=[{"role": "user", "content": prompt}])
    raw = re.sub(r"^```(?:json)?\s*", "", msg.content[0].text.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def analyze_timeline(client, current_timeline, tae_result, today):
    prompt = textwrap.dedent(f"""
        Today is {today}.
        Current TAE/TMTG merger timeline:
        {json.dumps(current_timeline, indent=2)}

        Latest TAE/TMTG status:
        {json.dumps(tae_result, indent=2)}

        Update timeline. Rules:
        - Never remove or reorder existing entries
        - Update status: "done" = completed, "pending" = in progress, "future" = not started
        - Only update detail text if new confirmed information exists
        - Return the complete array with all original entries

        Return JSON array only. No markdown.
    """).strip()

    msg = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM_PROMPT,
                                  messages=[{"role": "user", "content": prompt}])
    raw = re.sub(r"^```(?:json)?\s*", "", msg.content[0].text.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else current_timeline
    except json.JSONDecodeError:
        return current_timeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",    default=DATA_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[ERROR] ANTHROPIC_API_KEY not set.")

    client = anthropic.Anthropic(api_key=api_key)
    today  = datetime.date.today().isoformat()

    print(f"[fusion-watch-updater] {today} | model={MODEL} | dry_run={args.dry_run}\n")

    with open(args.data, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # CRITICAL: locked section is never modified
    locked  = data["locked"]
    dynamic = data["dynamic"]

    print("  Fetching global headlines...")
    global_items = fetch_global_items()
    print(f"  {len(global_items)} global items\n")

    company_results = {}
    for company in COMPANIES:
        print(f"  [{company['id'].upper()}] Fetching RSS...")
        items  = fetch_feed_items(company)
        print(f"           {len(items)} items | Calling Claude...")
        current = dynamic["companies"].get(company["id"], {})
        result  = analyze_company(client, company, current, items, today)
        if result:
            result["name"] = current.get("name", company["name"])
            result["sub"]  = current.get("sub", "")
            company_results[company["id"]] = result
            dynamic["companies"][company["id"]].update(result)
            print(f"           OK — {result.get('status_label','?')}")
        else:
            print(f"           SKIP")

    print("\n  Updating milestone banner...")
    banner = analyze_banner(client, company_results, global_items, today)
    if banner:
        dynamic["milestone_banner"] = banner
        print(f"  OK — {banner.get('text','')[:80]}")

    print("\n  Updating TAE/TMTG timeline...")
    dynamic["timeline"] = analyze_timeline(client, dynamic["timeline"], company_results.get("tae", {}), today)
    print(f"  OK — {len(dynamic['timeline'])} entries")

    dynamic["last_auto_update"]    = today
    dynamic["auto_update_summary"] = f"Auto-updated {len(company_results)}/6 companies via Claude + RSS. Locked fields unchanged."

    output = {"locked": locked, "dynamic": dynamic}

    if args.dry_run:
        print("\n[DRY RUN] Preview:")
        preview = json.dumps(output, indent=2)
        print(preview[:1500] + "..." if len(preview) > 1500 else preview)
    else:
        with open(args.data, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False)
        print(f"\n  OK {args.data} written")

    print("\n[DONE]")


if __name__ == "__main__":
    main()
