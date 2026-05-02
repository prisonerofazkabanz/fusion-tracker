#!/usr/bin/env python3
"""
Grand Strategy Auto-Updater with Monthly Briefing Email
========================================================
Fetches RSS feeds, calls Claude for analysis, injects updated HTML,
then generates a full intelligence briefing and emails it via Gmail SMTP.

Usage:
  python update_grand_strategy.py [--html PATH] [--dry-run]

Required env var:
  ANTHROPIC_API_KEY

Email env vars (optional):
  GMAIL_ADDRESS
  GMAIL_APP_PASSWORD
  BRIEFING_TO_EMAIL
"""

import os
import re
import sys
import json
import argparse
import textwrap
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

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
            "Track: Iranian regime fragmentation after Feb 2026 decapitation strike, "
            "naval blockade status, Iranian oil exports (target: zero), proxy network "
            "activity in Lebanon/Yemen, successor faction power struggle."
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
            "Track: Ras Laffan and Mesaieed LNG facilities after Mar 2026 strikes, "
            "Qatar energy export volumes, LNG spot prices, QatarEnergy repair timeline, "
            "Asia LNG alternatives, Qatar diplomatic posture."
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
            "Track: Ukraine strikes on Russian oil/refinery infrastructure, "
            "shadow fleet seizure operations, Russia export capacity changes, "
            "India/China crude absorption, refinery rebuild, sanctions enforcement."
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
            "Track: Venezuelan post-Maduro political transition, PDVSA operational "
            "status under US oversight, Venezuelan crude exports, China response, "
            "Defense Production Act energy redirection, Western Hemisphere energy deals."
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
            "Track: US chokepoint control — Malacca (Philippines/Indonesia pacts), "
            "Gibraltar (Morocco deal), Hormuz (post-Iran), Panama Canal. "
            "Monitor China naval response, Morocco deal ratification, Indonesia politics."
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
            "Track: US LNG export dominance, Maritime Action Plan compliance, "
            "bilateral energy deals (Ecuador, Colombia, Chile, Argentina, Panama, Indonesia), "
            "Greenland resource access, OPEC+ response, EU energy dependence."
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

SYSTEM_PROMPT = (
    "You are an intelligence analyst updating a classified-style web tracker. "
    "Concise, precise, analytical tone. "
    "Output ONLY valid JSON with the exact keys requested. "
    "Never add markdown code fences or extra text outside the JSON object."
)

BRIEFING_SYSTEM = (
    "You are a senior intelligence analyst writing a classified monthly briefing. "
    "Style: precise, assertive, present-tense. No hedging. No filler. "
    "Use markdown tables where data is comparative. Total length: 900-1100 words."
)


# ---------------------------------------------------------------------------
# RSS INGESTION
# ---------------------------------------------------------------------------

def fetch_feed_items(topic):
    items = []
    keywords = [k.lower() for k in topic["keywords"]]
    for feed_url in topic["feeds"]:
        try:
            r = requests.get(
                feed_url,
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 GrandStrategyBot/1.0"},
            )
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:20]:
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                text    = (title + " " + summary).lower()
                if any(kw in text for kw in keywords):
                    items.append({
                        "title":   title,
                        "summary": BeautifulSoup(summary, "html.parser").get_text()[:400],
                        "date":    entry.get("published", entry.get("updated", "")),
                        "source":  feed.feed.get("title", feed_url),
                        "link":    entry.get("link", ""),
                    })
        except Exception as exc:
            print(f"  [WARN] Feed {feed_url}: {exc}", file=sys.stderr)

    seen, unique = set(), []
    for item in items:
        key = item["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:MAX_FEED_ITEMS]


# ---------------------------------------------------------------------------
# CLAUDE — PER-TOPIC ANALYSIS
# ---------------------------------------------------------------------------

def analyze_topic(client, topic, feed_items, today):
    items_text = "\n".join(
        f"[{i+1}] {it['date']} | {it['source']}\n    {it['title']}\n    {it['summary']}"
        for i, it in enumerate(feed_items)
    ) or "(No RSS items — use training knowledge for latest status.)"

    badge_map = json.dumps(topic["badge_options"], indent=2)

    prompt = textwrap.dedent(f"""
        Today is {today}. Updating the "{topic['name']}" story thread.

        STORY CONTEXT:
        {topic['context']}

        RECENT FEED ({len(feed_items)} items):
        {items_text}

        Return a JSON object with exactly these keys:
        {{
          "badge_class": "<CSS class from BADGE OPTIONS>",
          "badge_text": "<short status label>",
          "card_summary_html": "<p class='card-summary'>2-3 sentence present-tense paragraph</p>",
          "metrics": [
            {{"value": "...", "label": "UPPERCASE LABEL"}},
            {{"value": "...", "label": "UPPERCASE LABEL"}},
            {{"value": "...", "label": "UPPERCASE LABEL"}}
          ],
          "card_analysis_html": "<p class='card-analysis'>Monitor: one sentence.</p>",
          "signal_or_flag_html": "",
          "feed_items": [
            {{
              "date": "YYYY-MM-DD",
              "tag_class": "tag-{topic['id']}",
              "tag_label": "LABEL",
              "title": "headline (max 120 chars)",
              "source": "source name"
            }}
          ]
        }}

        BADGE OPTIONS:
        {badge_map}

        Return ONLY the JSON. No markdown fences. No extra text.
    """).strip()

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  [WARN] JSON parse failed for {topic['id']}: {exc}", file=sys.stderr)
        return {}


def analyze_banner_and_feed(client, all_results, today):
    summaries = []
    for tid, r in all_results.items():
        if r:
            text = BeautifulSoup(r.get("card_summary_html", ""), "html.parser").get_text()
            summaries.append(f"[{tid.upper()}] {r.get('badge_text', '')} | {text[:200]}")

    prompt = textwrap.dedent(f"""
        Today is {today}. Based on these thread summaries:
        {chr(10).join(summaries)}

        Return JSON:
        {{
          "banner_html": "<span class='banner-tag'>Latest Signal</span><span class='banner-text'>highlights here</span>",
          "merged_feed": [
            {{
              "date": "YYYY-MM-DD",
              "tag_class": "tag-energy",
              "tag_label": "ENERGY",
              "title": "headline",
              "source": "Prisoner Intel"
            }}
          ]
        }}

        merged_feed: 5 most significant items, most recent first.
        Return ONLY JSON. No markdown fences.
    """).strip()

    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# CLAUDE — MONTHLY BRIEFING GENERATOR
# ---------------------------------------------------------------------------

def generate_briefing(client, all_results, today):
    topic_data = []
    for tid, r in all_results.items():
        if r:
            topic_data.append({
                "id":      tid,
                "name":    next((t["name"] for t in TOPICS if t["id"] == tid), tid),
                "status":  r.get("badge_text", ""),
                "summary": BeautifulSoup(r.get("card_summary_html", ""), "html.parser").get_text().strip(),
                "monitor": BeautifulSoup(r.get("card_analysis_html", ""), "html.parser").get_text().strip(),
                "metrics": r.get("metrics", []),
            })

    today_dt = datetime.date.today()
    if today_dt.month == 12:
        next_update = today_dt.replace(year=today_dt.year + 1, month=1, day=1)
    else:
        next_update = today_dt.replace(month=today_dt.month + 1, day=1)

    prompt = textwrap.dedent(f"""
        Today is {today}. Write the Prisoner Intelligence Grand Strategy monthly briefing.

        THREAD DATA:
        {json.dumps(topic_data, indent=2)}

        Use this exact markdown structure:

        # American Grand Strategy -- Monthly Update
        ### Intelligence Briefing -- Prisoner | Updated {today}

        ---

        ## EXECUTIVE SUMMARY
        [3 paragraphs: lead development / energy-competitor causal links / forward posture]

        ---

        ## I. ENERGY MONOPOLY STATUS
        [Metrics table then 1 paragraph]

        | Metric | Value | Change |
        |---|---|---|

        ## II. COMPETITOR DEGRADATION MATRIX

        | Target | Status | Key Metric | Next Trigger |
        |---|---|---|---|

        [1 paragraph synthesis]

        ## III. CHOKEPOINT CONTROL

        | Strait | Status | Strategic Value | Risk Factor |
        |---|---|---|---|

        [1 paragraph]

        ## IV. FORWARD INDICATORS -- {next_update.strftime('%B %Y')}
        1. [specific watchpoint]
        2. [specific watchpoint]
        3. [specific watchpoint]
        4. [specific watchpoint]
        5. [specific watchpoint]
        6. [specific watchpoint]
        7. [specific watchpoint]

        ## V. CONFIDENCE ASSESSMENT
        [3 sentences on sourcing quality and data gaps]

        ---
        *AUTO-GENERATED -- Prisoner Intelligence // Grand Strategy Module*
        *Next scheduled update: {next_update.isoformat()}*

        Rules: assertive present-tense, no hedging, 900-1100 words, proper markdown tables.
    """).strip()

    msg = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=BRIEFING_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# EMAIL -- MINIMAL MARKDOWN TO HTML
# ---------------------------------------------------------------------------

def markdown_to_html(md):
    """Convert markdown to HTML for email. No external dependencies."""
    lines    = md.split("\n")
    out      = []
    in_table = False
    in_list  = False

    for line in lines:
        # --- Tables ---
        if line.startswith("|"):
            if not in_table:
                out.append("<table>")
                in_table = True
            # Skip separator rows like |---|---|
            if re.match(r"^\|[-| :]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            # Use <th> for first row of each table, <td> after
            if out[-1] == "<table>":
                tag = "th"
            else:
                tag = "td"
            row = "<tr>" + "".join("<" + tag + ">" + c + "</" + tag + ">" for c in cells) + "</tr>"
            out.append(row)
            continue
        else:
            if in_table:
                out.append("</table>")
                in_table = False

        # --- Headings ---
        if line.startswith("### "):
            out.append("<h3>" + line[4:] + "</h3>")
            continue
        if line.startswith("## "):
            out.append("<h2>" + line[3:] + "</h2>")
            continue
        if line.startswith("# "):
            out.append("<h1>" + line[2:] + "</h1>")
            continue

        # --- Numbered list ---
        if re.match(r"^\d+\. ", line):
            if not in_list:
                out.append("<ol>")
                in_list = True
            item_text = re.sub(r"^\d+\.\s*", "", line)
            out.append("<li>" + item_text + "</li>")
            continue
        else:
            if in_list:
                out.append("</ol>")
                in_list = False

        # --- HR ---
        if line.strip() in ("---", "***", "___"):
            out.append("<hr>")
            continue

        # --- Inline formatting ---
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         line)
        line = re.sub(r"`(.+?)`",       r"<code>\1</code>",      line)

        # --- Blank line or paragraph ---
        if not line.strip():
            out.append("<br>")
        else:
            out.append("<p>" + line + "</p>")

    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ol>")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# EMAIL SENDER
# ---------------------------------------------------------------------------

def send_briefing_email(briefing_md, today):
    """Send the monthly briefing via Gmail SMTP + App Password."""
    gmail_address  = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    to_email       = os.environ.get("BRIEFING_TO_EMAIL")

    if not gmail_address or not gmail_password:
        print("  [WARN] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set -- skipping email.", file=sys.stderr)
        return False
    if not to_email:
        print("  [WARN] BRIEFING_TO_EMAIL not set -- skipping email.", file=sys.stderr)
        return False

    subject = "Prisoner Intelligence // Grand Strategy -- " + today

    html_body = markdown_to_html(briefing_md)
    html_full = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
body {
    margin: 0; padding: 0;
    background-color: #080c10;
    color: #c8d8e8;
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    line-height: 1.7;
}
.wrapper {
    max-width: 720px;
    margin: 0 auto;
    padding: 32px 28px 40px;
    background: #0d1219;
    border-left: 3px solid #FF6B1A;
}
h1 { font-size: 20px; color: #FF6B1A; text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 4px; }
h2 { font-size: 11px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase;
     color: #FF6B1A; margin: 28px 0 8px; padding-bottom: 5px;
     border-bottom: 1px solid rgba(255,107,26,0.25); }
h3 { font-size: 10px; color: #4a6070; letter-spacing: 0.12em; margin: 0 0 24px; font-weight: 400; }
p  { margin: 0 0 12px; }
strong { color: #e8f4ff; }
em     { color: #4a6070; font-style: normal; font-size: 11px; }
code   { color: #00D4A0; }
hr { border: none; border-top: 1px solid rgba(255,107,26,0.18); margin: 24px 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 12px; }
th { text-align: left; padding: 7px 11px; color: #FF6B1A; font-size: 10px;
     letter-spacing: 0.1em; text-transform: uppercase;
     border-bottom: 1px solid rgba(255,107,26,0.3);
     background: rgba(255,107,26,0.05); }
td { padding: 7px 11px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }
ol { padding-left: 18px; margin: 6px 0 14px; }
li { margin: 5px 0; line-height: 1.6; }
.footer {
    margin-top: 32px;
    padding-top: 14px;
    border-top: 1px solid rgba(255,107,26,0.12);
    font-size: 10px;
    color: #2a3a4a;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
</style>
</head>
<body>
<div class="wrapper">
""" + html_body + """
<div class="footer">
  Automated &middot; GitHub Actions + Claude &middot; Grand Strategy Module
</div>
</div>
</body>
</html>"""

    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = gmail_address
        msg["To"]      = to_email
        msg.attach(MIMEText(briefing_md, "plain"))
        msg.attach(MIMEText(html_full,   "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())

        print("  OK Briefing emailed to " + to_email)
        return True

    except Exception as exc:
        print("  FAIL Email error: " + str(exc), file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# HTML MARKER INJECTION
# ---------------------------------------------------------------------------

def replace_marker(html, marker, new_content):
    pattern = re.compile(
        r"(<!--\s*GS:START:" + re.escape(marker) + r"\s*-->)"
        r"(.*?)"
        r"(<!--\s*GS:END:"   + re.escape(marker) + r"\s*-->)",
        re.DOTALL,
    )
    result, count = pattern.subn(r"\1\n    " + new_content + r"\n    \3", html)
    if count == 0:
        print("  [WARN] Marker not found: " + marker, file=sys.stderr)
    return result


def build_card_html(result):
    metrics_html = "\n".join(
        '          <div class="metric">'
        '<span class="metric-value">' + m["value"] + '</span>'
        '<span class="metric-label">' + m["label"] + '</span>'
        '</div>'
        for m in result.get("metrics", [])
    )
    return (
        "\n        " + result.get("card_summary_html", "")
        + '\n        <div class="metrics-row">\n'
        + metrics_html
        + '\n        </div>\n        '
        + result.get("card_analysis_html", "")
        + "\n        "
        + result.get("signal_or_flag_html", "")
    )


def build_badge_html(result):
    cls  = result.get("badge_class", "badge-dim")
    text = result.get("badge_text", "UNKNOWN")
    return '<div class="badge ' + cls + '">' + text + '</div>'


def build_feed_html(items):
    rows = []
    for it in items:
        rows.append(
            '<div class="feed-item">'
            '<div class="feed-date">'   + it.get("date", "")   + '</div>'
            '<div class="feed-title">'
            '<div><span class="feed-tag ' + it.get("tag_class", "") + '">'
            + it.get("tag_label", "") + '</span></div>'
            + it.get("title", "")
            + '</div>'
            '<div class="feed-source">' + it.get("source", "") + '</div>'
            '</div>'
        )
    return "\n    ".join(rows)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Grand Strategy auto-updater")
    parser.add_argument("--html",    default=HTML_FILE, help="Path to grand-strategy.html")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no file writes or emails")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[ERROR] ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)
    today  = datetime.date.today().isoformat()
    now    = datetime.datetime.now().strftime("%H:%M")

    print("[grand-strategy-updater]", today, now, "| model=" + MODEL, "| dry_run=" + str(args.dry_run))
    print()

    # Load HTML
    with open(args.html, "r", encoding="utf-8") as fh:
        html = fh.read()

    # Per-topic fetch + analyze
    all_results = {}
    for topic in TOPICS:
        print("  [" + topic["id"].upper() + "] Fetching RSS...")
        items = fetch_feed_items(topic)
        print("           " + str(len(items)) + " relevant items | Calling Claude...")
        result = analyze_topic(client, topic, items, today)
        all_results[topic["id"]] = result
        if result:
            html = replace_marker(html, "card:"  + topic["id"], build_card_html(result))
            html = replace_marker(html, "badge:" + topic["id"], build_badge_html(result))
            print("           OK")
        else:
            print("           SKIP (empty result)")

    # Banner + merged feed
    print("\n  Synthesizing banner + feed...")
    global_result = analyze_banner_and_feed(client, all_results, today)
    if global_result:
        if "banner_html" in global_result:
            html = replace_marker(html, "banner", global_result["banner_html"])
        if "merged_feed" in global_result:
            html = replace_marker(html, "feed", build_feed_html(global_result["merged_feed"]))
        print("  OK Banner + feed updated")

    # Timestamps
    html = replace_marker(html, "timestamp",   today)
    html = replace_marker(html, "refreshtime", now)
    print("  OK Timestamps ->", today, now)

    # Write HTML
    if args.dry_run:
        print("\n[DRY RUN] HTML not written.")
    else:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("\n  OK", args.html, "written (" + str(len(html)) + " bytes)")

    # Generate briefing
    print("\n  Generating monthly intelligence briefing...")
    briefing = generate_briefing(client, all_results, today)
    print("  OK Briefing generated (" + str(len(briefing)) + " chars)")

    if args.dry_run:
        print("\n[DRY RUN] Briefing preview:")
        print("-" * 60)
        print(briefing[:800])
        print("-" * 60)
        print("  Email not sent in dry-run mode.")
    else:
        print("\n  Sending briefing email...")
        send_briefing_email(briefing, today)

    print("\n[DONE]")


if __name__ == "__main__":
    main()
