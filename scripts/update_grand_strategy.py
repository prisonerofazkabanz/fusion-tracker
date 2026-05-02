#!/usr/bin/env python3
"""
Grand Strategy Auto-Updater
============================
Monthly automation: ingests RSS feeds → Claude analysis → injects updated
HTML into grand-strategy.html using GS:START/GS:END marker pairs.

Usage:
  python update_grand_strategy.py [--html PATH] [--dry-run]

Required env vars:
  ANTHROPIC_API_KEY   — your Anthropic API key (stored as GitHub Secret)

Optional env vars:
  ANTHROPIC_MODEL     — default: claude-opus-4-5
  MAX_FEED_ITEMS      — max RSS items to feed Claude per topic (default: 8)
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

HTML_FILE      = os.getenv("GS_HTML_PATH", "grand-strategy.html")
MODEL          = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
MAX_FEED_ITEMS = int(os.getenv("MAX_FEED_ITEMS", "8"))

TOPICS = [
    {
        "id": "iran",
        "name": "Iran Kill Chain",
        "badge_options": {
            "badge-red":    ["REGIME FRACTURED", "COLLAPSED", "CONFLICT"],
            "badge-orange": ["ESCALATING", "MONITORING", "ACTIVE"],
            "badge-yellow": ["MONITORING", "NEGOTIATING"],
            "badge-green":  ["STABLE", "DE-ESCALATING"],
            "badge-cyan":   ["ACTIVE", "DEVELOPING"],
        },
        "context": (
            "Track the status of: Iranian regime fragmentation after Feb 2026 decapitation strike, "
            "naval blockade status, Iranian oil exports (target: zero), proxy network activity "
            "in Lebanon/Yemen, successor faction power struggle, any return-to-market signals."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
        ],
        "keywords": ["iran", "iranian", "tehran", "irgc", "hormuz", "persian gulf", "supreme leader"],
    },
    {
        "id": "qatar",
        "name": "Qatar LNG Strike",
        "badge_options": {
            "badge-red":    ["OFFLINE", "DESTROYED"],
            "badge-yellow": ["MONITORING", "PARTIAL RECOVERY", "REPAIRING"],
            "badge-orange": ["ESCALATING", "ACTIVE"],
            "badge-green":  ["RESTORED", "OPERATIONAL"],
            "badge-cyan":   ["DEVELOPING"],
        },
        "context": (
            "Track the status of: Ras Laffan and Mesaieed LNG facilities after Mar 2, 2026 strikes, "
            "Qatar energy export volumes, global LNG spot prices, QatarEnergy repair timeline announcements, "
            "Asia LNG alternatives being pursued by Japan/South Korea/China, Qatar diplomatic posture."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
            "https://www.aljazeera.com/xml/rss/all.xml",
        ],
        "keywords": ["qatar", "lng", "ras laffan", "mesaieed", "qatarenergy", "liquefied natural gas"],
    },
    {
        "id": "russia",
        "name": "Russia Degradation",
        "badge_options": {
            "badge-cyan":   ["ACTIVE", "ONGOING"],
            "badge-orange": ["ESCALATING"],
            "badge-yellow": ["MONITORING"],
            "badge-red":    ["CONFLICT"],
            "badge-green":  ["PAUSED"],
        },
        "context": (
            "Track: Ukraine strikes on Russian oil/refinery infrastructure, shadow fleet seizure operations, "
            "Russia export capacity changes, India and China crude absorption of discounted Russian oil, "
            "refinery rebuild progress, sanctions enforcement, financial damage estimates."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://kyivindependent.com/feed",
            "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ],
        "keywords": ["russia", "russian oil", "shadow fleet", "refinery", "ukraine strike", "gazprom", "rosneft", "lukoil"],
    },
    {
        "id": "venezuela",
        "name": "Venezuela / Americas",
        "badge_options": {
            "badge-green":  ["SECURED", "STABLE"],
            "badge-orange": ["TRANSITION", "ACTIVE"],
            "badge-yellow": ["MONITORING"],
            "badge-cyan":   ["DEVELOPING"],
            "badge-red":    ["CONTESTED"],
        },
        "context": (
            "Track: Venezuelan post-Maduro political transition and successor government formation, "
            "PDVSA operational status under US oversight, Venezuelan crude export volumes, "
            "China response to supply disruption, US Defense Production Act energy redirection status, "
            "Western Hemisphere bilateral energy deal progress."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://rss.nytimes.com/services/xml/rss/nyt/Americas.xml",
            "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml",
        ],
        "keywords": ["venezuela", "maduro", "pdvsa", "caracas", "latin america oil", "western hemisphere energy"],
    },
    {
        "id": "chokepoints",
        "name": "Chokepoint Control",
        "badge_options": {
            "badge-green":  ["CONSOLIDATING", "CONTROLLED", "SECURED"],
            "badge-orange": ["ACTIVE", "UNDER PRESSURE"],
            "badge-yellow": ["MONITORING", "PARTIAL"],
            "badge-red":    ["CONTESTED"],
            "badge-cyan":   ["DEVELOPING"],
        },
        "context": (
            "Track status of US strategic chokepoint control: Strait of Malacca (Philippines/Indonesia pacts), "
            "Strait of Gibraltar (Morocco deal Apr 17), Strait of Hormuz (post-Iran degradation), "
            "Panama Canal (cooperation agreements). Monitor China naval response in South China Sea, "
            "Morocco deal ratification, Indonesia domestic politics, Chinese port operator presence in Panama."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/worldNews",
            "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ],
        "keywords": ["malacca", "strait", "gibraltar", "hormuz", "panama canal", "south china sea", "philippines", "indonesia"],
    },
    {
        "id": "energy",
        "name": "US Energy Monopoly",
        "badge_options": {
            "badge-orange": ["EXECUTING", "ACTIVE"],
            "badge-green":  ["ADVANCING", "CONSOLIDATING"],
            "badge-cyan":   ["DEVELOPING"],
            "badge-yellow": ["MONITORING"],
            "badge-red":    ["UNDER PRESSURE"],
        },
        "context": (
            "Track: US LNG export dominance (sole high-volume exporter post-Jan-Mar 2026), "
            "Maritime Action Plan tanker-build compliance by buyer nations, bilateral energy deal progress "
            "(Ecuador, Colombia, Chile, Argentina, Panama, Indonesia — $33B Apr 2026), "
            "Greenland resource access negotiations, OPEC+ response, EU energy dependence metrics, "
            "Defense Production Act implementation."
        ),
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.eia.gov/rss/press_releases.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        ],
        "keywords": ["lng export", "us energy", "maritime", "greenland", "opec", "natural gas", "energy deal", "energy dominance"],
    },
]

SYSTEM_PROMPT = textwrap.dedent("""
You are an intelligence analyst updating a classified-style web tracker.
You write in a concise, precise, analytical tone — no fluff, no hedging.
You output ONLY valid JSON with the exact keys requested.
Never add markdown code fences or extra text outside the JSON object.
""").strip()


def fetch_feed_items(topic):
    items = []
    keywords = [k.lower() for k in topic["keywords"]]
    for feed_url in topic["feeds"]:
        try:
            headers = {"User-Agent": "Mozilla/5.0 GrandStrategyBot/1.0"}
            r = requests.get(feed_url, timeout=12, headers=headers)
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:20]:
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                text    = (title + " " + summary).lower()
                if any(kw in text for kw in keywords):
                    items.append({
                        "title":   title,
                        "summary": BeautifulSoup(summary, "html.parser").get_text()[:400],
                        "date":    entry.get("published", entry.get("updated", "unknown date")),
                        "source":  feed.feed.get("title", feed_url),
                        "link":    entry.get("link", ""),
                    })
        except Exception as e:
            print(f"  [WARN] Feed {feed_url}: {e}", file=sys.stderr)
    seen, unique = set(), []
    for item in items:
        key = item["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:MAX_FEED_ITEMS]


def analyze_topic(client, topic, feed_items, today):
    items_text = "\n".join(
        f"[{i+1}] {it['date']} | {it['source']}\n    {it['title']}\n    {it['summary']}"
        for i, it in enumerate(feed_items)
    ) or "(No new RSS items found — use your knowledge up to your training cutoff for latest status.)"

    badge_map_text = json.dumps(
        {cls: options for cls, options in topic["badge_options"].items()}, indent=2
    )

    prompt = textwrap.dedent(f"""
    Today is {today}. You are updating the "{topic['name']}" story thread.

    STORY CONTEXT:
    {topic['context']}

    RECENT INTELLIGENCE FEED ({len(feed_items)} items):
    {items_text}

    Return a JSON object with these exact keys:
    {{
      "badge_class": "<CSS class from BADGE OPTIONS>",
      "badge_text": "<short status label>",
      "card_summary_html": "<2-3 sentence <p class='card-summary'> paragraph, present-tense intel tone>",
      "metrics": [
        {{"value": "<concise>", "label": "<UPPERCASE 1-3 WORDS>"}},
        {{"value": "<concise>", "label": "<UPPERCASE 1-3 WORDS>"}},
        {{"value": "<concise>", "label": "<UPPERCASE 1-3 WORDS>"}}
      ],
      "card_analysis_html": "<1 sentence <p class='card-analysis'> starting with 'Monitor:'>",
      "signal_or_flag_html": "<optional <div class='signal-flag'> or <div class='intel-flag'>, else empty string>",
      "feed_items": [
        {{"date": "YYYY-MM-DD", "tag_class": "tag-{topic['id']}", "tag_label": "<LABEL>", "title": "<headline max 120 chars>", "source": "<source>"}}
      ]
    }}

    BADGE OPTIONS:
    {badge_map_text}

    Return ONLY the JSON object. No markdown. No extra text.
    """).strip()

    message = client.messages.create(
        model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse failed for {topic['id']}: {e}", file=sys.stderr)
        return {}


def analyze_banner_and_feed(client, all_results, today):
    summaries = []
    for tid, r in all_results.items():
        if r:
            summaries.append(f"[{tid.upper()}] badge={r.get('badge_text','?')} | {BeautifulSoup(r.get('card_summary_html',''), 'html.parser').get_text()[:200]}")

    prompt = textwrap.dedent(f"""
    Today is {today}. Based on these story-thread summaries:
    {chr(10).join(summaries)}

    Return JSON:
    {{
      "banner_html": "<inner HTML for banner: <span class='banner-tag'>Latest Signal</span> + <span class='banner-text'>...</span>>",
      "merged_feed": [
        {{"date": "YYYY-MM-DD", "tag_class": "<e.g. tag-energy>", "tag_label": "<ENERGY>", "title": "<headline>", "source": "Peterson Intel"}}
      ]
    }}

    merged_feed: 5 most significant recent developments across all threads, most recent first.
    Return ONLY the JSON object. No markdown.
    """).strip()

    message = client.messages.create(
        model=MODEL, max_tokens=600, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def replace_marker(html, marker, new_content):
    pattern = re.compile(
        rf"(<!--\s*GS:START:{re.escape(marker)}\s*-->)(.*?)(<!--\s*GS:END:{re.escape(marker)}\s*-->)",
        re.DOTALL,
    )
    result, count = pattern.subn(rf"\1\n    {new_content}\n    \3", html)
    if count == 0:
        print(f"  [WARN] Marker not found: {marker}", file=sys.stderr)
    return result


def build_card_html(result):
    metrics_html = "\n".join(
        f'          <div class="metric"><span class="metric-value">{m["value"]}</span>'
        f'<span class="metric-label">{m["label"]}</span></div>'
        for m in result.get("metrics", [])
    )
    return (
        f'\n        {result.get("card_summary_html","")}'
        f'\n        <div class="metrics-row">\n{metrics_html}\n        </div>'
        f'\n        {result.get("card_analysis_html","")}'
        f'\n        {result.get("signal_or_flag_html","")}'
    )


def build_badge_html(result):
    return f'<div class="badge {result.get("badge_class","badge-dim")}">{result.get("badge_text","UNKNOWN")}</div>'


def build_feed_html(items):
    rows = []
    for it in items:
        rows.append(textwrap.dedent(f"""
            <div class="feed-item">
              <div class="feed-date">{it.get("date","")}</div>
              <div class="feed-title">
                <div><span class="feed-tag {it.get("tag_class","")}">{it.get("tag_label","")}</span></div>
                {it.get("title","")}
              </div>
              <div class="feed-source">{it.get("source","")}</div>
            </div>
        """).strip())
    return "\n    ".join(rows)

def send_briefing_email(briefing_md: str, today: str) -> bool:
    """Send the monthly briefing via Gmail SMTP + App Password. No third-party service needed."""
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText

    gmail_address   = os.environ.get("GMAIL_ADDRESS")
    gmail_app_pass  = os.environ.get("GMAIL_APP_PASSWORD")
    to_email        = os.environ.get("BRIEFING_TO_EMAIL")

    if not all([gmail_address, gmail_app_pass, to_email]):
        print("  [WARN] GMAIL_ADDRESS / GMAIL_APP_PASSWORD / BRIEFING_TO_EMAIL not set — skipping email.", file=sys.stderr)
        return False

    subject = f"Peterson Intelligence // Grand Strategy — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Peterson Intelligence <{gmail_address}>"
    msg["To"]      = to_email

    # Plain text part (Proton will always show this as fallback)
    msg.attach(MIMEText(briefing_md, "plain"))

    # HTML part — dark intel styling matching the site
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><style>
  body {{
    margin:0; padding:0;
    background-color:#080c10;
    color:#c8d8e8;
    font-family:'Courier New',Courier,monospace;
    font-size:13px; line-height:1.7;
  }}
  .wrapper {{
    max-width:720px; margin:0 auto;
    padding:32px 28px 40px;
    background:#0d1219;
    border-left:3px solid #FF6B1A;
  }}
  h1  {{ font-size:20px; color:#FF6B1A; text-transform:uppercase; letter-spacing:.04em; margin:0 0 2px; }}
  h2  {{ font-size:11px; font-weight:700; letter-spacing:.18em; text-transform:uppercase;
         color:#FF6B1A; margin:28px 0 8px; padding-bottom:5px;
         border-bottom:1px solid rgba(255,107,26,.25); }}
  h3  {{ font-size:10px; color:#4a6070; letter-spacing:.12em; margin:0 0 24px; font-weight:400; }}
  p   {{ margin:0 0 12px; }}
  strong {{ color:#e8f4ff; }}
  em  {{ color:#4a6070; font-style:normal; font-size:11px; }}
  hr  {{ border:none; border-top:1px solid rgba(255,107,26,.18); margin:24px 0; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0 18px; font-size:12px; }}
  th  {{ text-align:left; padding:7px 11px; color:#FF6B1A; font-size:10px;
         letter-spacing:.1em; text-transform:uppercase;
         border-bottom:1px solid rgba(255,107,26,.3);
         background:rgba(255,107,26,.05); }}
  td  {{ padding:7px 11px; border-bottom:1px solid rgba(255,255,255,.05); vertical-align:top; }}
  ol  {{ padding-left:18px; margin:6px 0 14px; }}
  li  {{ margin:5px 0; line-height:1.6; }}
  .footer {{ margin-top:32px; padding-top:14px;
             border-top:1px solid rgba(255,107,26,.12);
             font-size:10px; color:#2a3a4a; letter-spacing:.08em; text-transform:uppercase; }}
</style></head>
<body><div class="wrapper">
{_markdown_to_html(briefing_md)}
<div class="footer">
  Automated · GitHub Actions + Claude · Grand Strategy Module · Anonymous
</div>
</div></body></html>"""

    msg.attach(MIMEText(html_content, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(gmail_address, gmail_app_pass)
            server.sendmail(gmail_address, to_email, msg.as_string())
        print(f"  ✓ Briefing emailed → {to_email}")
        return True
    except Exception as e:
        print(f"  ✗ Email error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html",    default=HTML_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[ERROR] ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)
    today  = datetime.date.today().isoformat()
    now    = datetime.datetime.now().strftime("%H:%M")

    print(f"[grand-strategy-updater] {today} {now} | model={MODEL} | file={args.html}")

    with open(args.html, "r", encoding="utf-8") as f:
        html = f.read()

    all_results = {}
    for topic in TOPICS:
        print(f"  [{topic['id'].upper()}] Fetching RSS...")
        items = fetch_feed_items(topic)
        print(f"           {len(items)} relevant items | Calling Claude...")
        result = analyze_topic(client, topic, items, today)
        all_results[topic["id"]] = result
        if result:
            html = replace_marker(html, f"card:{topic['id']}", build_card_html(result))
            html = replace_marker(html, f"badge:{topic['id']}", build_badge_html(result))
            print(f"           ✓ Updated")
        else:
            print(f"           ✗ Skipped")

    print("\n  Synthesizing banner + feed...")
    global_result = analyze_banner_and_feed(client, all_results, today)
    if global_result:
        if "banner_html" in global_result:
            html = replace_marker(html, "banner", global_result["banner_html"])
        if "merged_feed" in global_result:
            html = replace_marker(html, "feed", build_feed_html(global_result["merged_feed"]))

    html = replace_marker(html, "timestamp",   today)
    html = replace_marker(html, "refreshtime", now)

    if args.dry_run:
        print("\n[DRY RUN] No file written.")
        print(html[:2000])
    else:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n[DONE] {args.html} updated ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
