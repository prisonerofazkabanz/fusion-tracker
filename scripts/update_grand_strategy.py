#!/usr/bin/env python3
"""
Grand Strategy Auto-Updater — with briefing email
"""

import os, re, sys, json, argparse, textwrap, datetime
import smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser, requests
from bs4 import BeautifulSoup
import anthropic

HTML_FILE      = os.getenv("GS_HTML_PATH", "grand-strategy.html")
MODEL          = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
MAX_FEED_ITEMS = int(os.getenv("MAX_FEED_ITEMS", "8"))

TOPICS = [
    {"id":"iran","name":"Iran Kill Chain","badge_options":{"badge-red":["REGIME FRACTURED","COLLAPSED","CONFLICT"],"badge-orange":["ESCALATING","MONITORING","ACTIVE"],"badge-yellow":["MONITORING","NEGOTIATING"],"badge-green":["STABLE","DE-ESCALATING"],"badge-cyan":["ACTIVE","DEVELOPING"]},"context":"Track the status of: Iranian regime fragmentation after Feb 2026 decapitation strike, naval blockade status, Iranian oil exports (target: zero), proxy network activity in Lebanon/Yemen, successor faction power struggle, any return-to-market signals.","feeds":["https://feeds.reuters.com/reuters/businessNews","https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml","https://www.aljazeera.com/xml/rss/all.xml","https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"],"keywords":["iran","iranian","tehran","irgc","hormuz","persian gulf","supreme leader"]},
    {"id":"qatar","name":"Qatar LNG Strike","badge_options":{"badge-red":["OFFLINE","DESTROYED"],"badge-yellow":["MONITORING","PARTIAL RECOVERY","REPAIRING"],"badge-orange":["ESCALATING","ACTIVE"],"badge-green":["RESTORED","OPERATIONAL"],"badge-cyan":["DEVELOPING"]},"context":"Track the status of: Ras Laffan and Mesaieed LNG facilities after Mar 2, 2026 strikes, Qatar energy export volumes, global LNG spot prices, QatarEnergy repair timeline announcements, Asia LNG alternatives being pursued by Japan/South Korea/China, Qatar diplomatic posture.","feeds":["https://feeds.reuters.com/reuters/businessNews","https://feeds.bbci.co.uk/news/world/middle_east/rss.xml","https://www.aljazeera.com/xml/rss/all.xml"],"keywords":["qatar","lng","ras laffan","mesaieed","qatarenergy","liquefied natural gas"]},
    {"id":"russia","name":"Russia Degradation","badge_options":{"badge-cyan":["ACTIVE","ONGOING"],"badge-orange":["ESCALATING"],"badge-yellow":["MONITORING"],"badge-red":["CONFLICT"],"badge-green":["PAUSED"]},"context":"Track: Ukraine strikes on Russian oil/refinery infrastructure, shadow fleet seizure operations, Russia export capacity changes, India and China crude absorption of discounted Russian oil, refinery rebuild progress, sanctions enforcement, financial damage estimates.","feeds":["https://feeds.reuters.com/reuters/businessNews","https://kyivindependent.com/feed","https://feeds.bbci.co.uk/news/world/europe/rss.xml","https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],"keywords":["russia","russian oil","shadow fleet","refinery","ukraine strike","gazprom","rosneft","lukoil"]},
    {"id":"venezuela","name":"Venezuela / Americas","badge_options":{"badge-green":["SECURED","STABLE"],"badge-orange":["TRANSITION","ACTIVE"],"badge-yellow":["MONITORING"],"badge-cyan":["DEVELOPING"],"badge-red":["CONTESTED"]},"context":"Track: Venezuelan post-Maduro political transition and successor government formation, PDVSA operational status under US oversight, Venezuelan crude export volumes, China response to supply disruption, US Defense Production Act energy redirection status, Western Hemisphere bilateral energy deal progress.","feeds":["https://feeds.reuters.com/reuters/businessNews","https://rss.nytimes.com/services/xml/rss/nyt/Americas.xml","https://feeds.bbci.co.uk/news/world/latin_america/rss.xml"],"keywords":["venezuela","maduro","pdvsa","caracas","latin america oil","western hemisphere energy"]},
    {"id":"chokepoints","name":"Chokepoint Control","badge_options":{"badge-green":["CONSOLIDATING","CONTROLLED","SECURED"],"badge-orange":["ACTIVE","UNDER PRESSURE"],"badge-yellow":["MONITORING","PARTIAL"],"badge-red":["CONTESTED"],"badge-cyan":["DEVELOPING"]},"context":"Track status of US strategic chokepoint control: Strait of Malacca (Philippines/Indonesia pacts), Strait of Gibraltar (Morocco deal Apr 17), Strait of Hormuz (post-Iran degradation), Panama Canal (cooperation agreements). Monitor China naval response in South China Sea, Morocco deal ratification, Indonesia domestic politics, Chinese port operator presence in Panama.","feeds":["https://feeds.reuters.com/reuters/worldNews","https://feeds.bbci.co.uk/news/world/asia/rss.xml","https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],"keywords":["malacca","strait","gibraltar","hormuz","panama canal","south china sea","philippines","indonesia"]},
    {"id":"energy","name":"US Energy Monopoly","badge_options":{"badge-orange":["EXECUTING","ACTIVE"],"badge-green":["ADVANCING","CONSOLIDATING"],"badge-cyan":["DEVELOPING"],"badge-yellow":["MONITORING"],"badge-red":["UNDER PRESSURE"]},"context":"Track: US LNG export dominance (sole high-volume exporter post-Jan-Mar 2026), Maritime Action Plan tanker-build compliance by buyer nations, bilateral energy deal progress (Ecuador, Colombia, Chile, Argentina, Panama, Indonesia — $33B Apr 2026), Greenland resource access negotiations, OPEC+ response, EU energy dependence metrics, Defense Production Act implementation.","feeds":["https://feeds.reuters.com/reuters/businessNews","https://www.eia.gov/rss/press_releases.xml","https://feeds.bbci.co.uk/news/business/rss.xml","https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"],"keywords":["lng export","us energy","maritime","greenland","opec","natural gas","energy deal","energy dominance"]},
]

SYSTEM_PROMPT = "You are an intelligence analyst updating a classified-style web tracker. Concise, precise, analytical. Output ONLY valid JSON. No markdown fences."
BRIEFING_SYSTEM = "You are a senior intelligence analyst writing a classified monthly briefing. Precise, assertive, present-tense. No hedging. 900-1100 words."


def fetch_feed_items(topic):
    items, keywords = [], [k.lower() for k in topic["keywords"]]
    for url in topic["feeds"]:
        try:
            r = requests.get(url, timeout=12, headers={"User-Agent":"Mozilla/5.0 GrandStrategyBot/1.0"})
            feed = feedparser.parse(r.content)
            for e in feed.entries[:20]:
                t, s = e.get("title",""), e.get("summary", e.get("description",""))
                if any(kw in (t+" "+s).lower() for kw in keywords):
                    items.append({"title":t,"summary":BeautifulSoup(s,"html.parser").get_text()[:400],"date":e.get("published",e.get("updated","")),"source":feed.feed.get("title",url),"link":e.get("link","")})
        except Exception as ex:
            print(f"  [WARN] {url}: {ex}", file=sys.stderr)
    seen, unique = set(), []
    for item in items:
        k = item["title"][:60].lower()
        if k not in seen: seen.add(k); unique.append(item)
    return unique[:MAX_FEED_ITEMS]


def analyze_topic(client, topic, items, today):
    items_text = "\n".join(f"[{i+1}] {it['date']} | {it['source']}\n    {it['title']}\n    {it['summary']}" for i,it in enumerate(items)) or "(No RSS items — use training knowledge.)"
    prompt = textwrap.dedent(f"""
    Today is {today}. Updating "{topic['name']}".
    CONTEXT: {topic['context']}
    FEED ({len(items)} items): {items_text}
    Return JSON: {{"badge_class":"<from BADGE OPTIONS>","badge_text":"<label>","card_summary_html":"<p class='card-summary'>...</p>","metrics":[{{"value":"","label":""}},{{"value":"","label":""}},{{"value":"","label":""}}],"card_analysis_html":"<p class='card-analysis'>Monitor: ...</p>","signal_or_flag_html":"","feed_items":[{{"date":"YYYY-MM-DD","tag_class":"tag-{topic['id']}","tag_label":"","title":"","source":""}}]}}
    BADGE OPTIONS: {json.dumps(topic['badge_options'])}
    ONLY JSON. No markdown.
    """).strip()
    msg = client.messages.create(model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT, messages=[{"role":"user","content":prompt}])
    raw = re.sub(r"^```(?:json)?\s*","",msg.content[0].text.strip(),flags=re.MULTILINE)
    raw = re.sub(r"\s*```$","",raw,flags=re.MULTILINE)
    try: return json.loads(raw)
    except: return {}


def analyze_banner_and_feed(client, all_results, today):
    sums = [f"[{tid.upper()}] {r.get('badge_text','')} | {BeautifulSoup(r.get('card_summary_html',''),'html.parser').get_text()[:200]}" for tid,r in all_results.items() if r]
    prompt = f"Today {today}. Summaries:\n{chr(10).join(sums)}\nReturn JSON: {{\"banner_html\":\"<span class='banner-tag'>Latest Signal</span><span class='banner-text'>...</span>\",\"merged_feed\":[{{\"date\":\"YYYY-MM-DD\",\"tag_class\":\"tag-X\",\"tag_label\":\"\",\"title\":\"\",\"source\":\"Peterson Intel\"}}]}}\n5 most significant items. ONLY JSON."
    msg = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM_PROMPT, messages=[{"role":"user","content":prompt}])
    raw = re.sub(r"^```(?:json)?\s*","",msg.content[0].text.strip(),flags=re.MULTILINE)
    raw = re.sub(r"\s*```$","",raw,flags=re.MULTILINE)
    try: return json.loads(raw)
    except: return {}


def generate_briefing(client, all_results, today):
    topic_data = []
    for tid, r in all_results.items():
        if r:
            topic_data.append({"id":tid,"name":next((t["name"] for t in TOPICS if t["id"]==tid),tid),"status":r.get("badge_text",""),"summary":BeautifulSoup(r.get("card_summary_html",""),"html.parser").get_text().strip(),"monitor":BeautifulSoup(r.get("card_analysis_html",""),"html.parser").get_text().strip(),"metrics":r.get("metrics",[])})
    dt = datetime.date.today()
    next_update = dt.replace(year=dt.year+1,month=1,day=1) if dt.month==12 else dt.replace(month=dt.month+1,day=1)
    prompt = textwrap.dedent(f"""
    Today is {today}. Write the monthly Peterson Intelligence Grand Strategy briefing.
    THREAD DATA: {json.dumps(topic_data, indent=2)}

    Structure (markdown):
    # American Grand Strategy — Monthly Update
    ### Intelligence Briefing — Peterson | Updated {today}
    ---
    ## EXECUTIVE SUMMARY
    [3 paragraphs: lead development / energy-competitor causal links / forward posture]
    ---
    ## I. ENERGY MONOPOLY STATUS
    [Metrics table: | Metric | Value | Change | then 1 paragraph]
    ## II. COMPETITOR DEGRADATION MATRIX
    | Target | Status | Key Metric | Next Trigger |
    [Iran, Qatar LNG, Russia, Venezuela rows + 1 paragraph synthesis]
    ## III. CHOKEPOINT CONTROL
    | Strait | Status | Strategic Value | Risk Factor |
    [4 rows + 1 paragraph]
    ## IV. FORWARD INDICATORS — {next_update.strftime('%B %Y')}
    [7 numbered watchpoints from monitor fields — specific actors/locations/thresholds]
    ## V. CONFIDENCE ASSESSMENT
    [3 sentences on sourcing quality and data gaps]
    ---
    *AUTO-GENERATED — Peterson Intelligence // Grand Strategy Module*
    *Next scheduled update: {next_update.isoformat()}*

    Rules: assertive present-tense, no hedging, 900-1100 words, proper markdown tables.
    """).strip()
    msg = client.messages.create(model=MODEL, max_tokens=2500, system=BRIEFING_SYSTEM, messages=[{"role":"user","content":prompt}])
    return msg.content[0].text.strip()


def _markdown_to_html(md):
    lines, out, in_table, in_list = md.split("\n"), [], False, False
    for line in lines:
        if line.startswith("|"):
            if not in_table: out.append("<table>"); in_table=True
            if re.match(r"^\|[-| :]+\|$",line): continue
            cells=[c.strip() for c in line.strip("|").split("|")]
            tag="th" if not any("<td" in r for r in out[-5:]) else "td"
            out.append("<tr>"+"".join(f"<{tag}>{c}</{tag}>" for c in cells)+"</tr>"); continue
        else:
            if in_table: out.append("</table>"); in_table=False
        if line.startswith("### "): out.append(f"<h3>{line[4:]}</h3>"); continue
        if line.startswith("## "): out.append(f"<h2>{line[3:]}</h2>"); continue
        if line.startswith("# "): out.append(f"<h1>{line[2:]}</h1>"); continue
        if re.match(r"^\d+\. ",line):
            if not in_list: out.append("<ol>"); in_list=True
            _li_text = re.sub(r"^\d+\.\s*", "", line): out.append("<li>" + _li_text + "</li>"); continue
        else:
            if in_list: out.append("</ol>"); in_list=False
        if line.strip() in ("---","***","___"): out.append("<hr>"); continue
        line=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",line)
        line=re.sub(r"\*(.+?)\*",r"<em>\1</em>",line)
        line=re.sub(r"`(.+?)`",r"<code>\1</code>",line)
        out.append("<br>" if not line.strip() else f"<p>{line}</p>")
    if in_table: out.append("</table>")
    if in_list: out.append("</ol>")
    return "\n".join(out)


def send_briefing_email(briefing_md: str, today: str) -> bool:
    """Send the monthly briefing via Gmail SMTP."""
    gmail_address  = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    to_email       = os.environ.get("BRIEFING_TO_EMAIL")

    if not gmail_address or not gmail_password:
        print("  [WARN] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — skipping.", file=sys.stderr)
        return False
    if not to_email:
        print("  [WARN] BRIEFING_TO_EMAIL not set — skipping.", file=sys.stderr)
        return False

    subject      = f"Peterson Intelligence // Grand Strategy — {today}"
    html_content = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ background:#080c10; color:#c8d8e8; font-family:'Courier New',monospace; font-size:13px; line-height:1.7; }}
  .wrapper {{ max-width:720px; margin:0 auto; padding:32px 28px 40px; background:#0d1219; border-left:3px solid #FF6B1A; }}
  h1 {{ color:#FF6B1A; font-size:20px; text-transform:uppercase; }}
  h2 {{ color:#FF6B1A; font-size:11px; letter-spacing:0.18em; text-transform:uppercase; border-bottom:1px solid rgba(255,107,26,0.25); padding-bottom:6px; }}
  p {{ color:#c8d8e8; margin:0 0 12px; }}
  strong {{ color:#e8f4ff; }} code {{ color:#00D4A0; }}
</style></head><body>
<div class="wrapper">{_markdown_to_html(briefing_md)}</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = gmail_address
        msg["To"]      = to_email
        msg.attach(MIMEText(briefing_md,  "plain"))
        msg.attach(MIMEText(html_content, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())
        print(f"  ✓ Briefing emailed → {to_email}")
        return True
    except Exception as e:
        print(f"  ✗ Email error: {e}", file=sys.stderr)
        return False


def replace_marker(html,marker,content):
    pat=re.compile(rf"(<!--\s*GS:START:{re.escape(marker)}\s*-->)(.*?)(<!--\s*GS:END:{re.escape(marker)}\s*-->)",re.DOTALL)
    r,n=pat.subn(rf"\1\n    {content}\n    \3",html)
    if n==0: print(f"  [WARN] Marker not found: {marker}",file=sys.stderr)
    return r

def build_card_html(r):
    m="\n".join(f'          <div class="metric"><span class="metric-value">{x["value"]}</span><span class="metric-label">{x["label"]}</span></div>' for x in r.get("metrics",[]))
    return f'\n        {r.get("card_summary_html","")}\n        <div class="metrics-row">\n{m}\n        </div>\n        {r.get("card_analysis_html","")}\n        {r.get("signal_or_flag_html","")}'

def build_badge_html(r):
    return f'<div class="badge {r.get("badge_class","badge-dim")}">{r.get("badge_text","UNKNOWN")}</div>'

def build_feed_html(items):
    rows=[]
    for it in items:
        rows.append(f'<div class="feed-item"><div class="feed-date">{it.get("date","")}</div><div class="feed-title"><div><span class="feed-tag {it.get("tag_class","")}">{it.get("tag_label","")}</span></div>{it.get("title","")}</div><div class="feed-source">{it.get("source","")}</div></div>')
    return "\n    ".join(rows)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--html",default=HTML_FILE); parser.add_argument("--dry-run",action="store_true"); args=parser.parse_args()
    api_key=os.environ.get("ANTHROPIC_API_KEY")
    if not api_key: sys.exit("[ERROR] ANTHROPIC_API_KEY not set.")
    client=anthropic.Anthropic(api_key=api_key)
    today=datetime.date.today().isoformat(); now=datetime.datetime.now().strftime("%H:%M")
    print(f"[grand-strategy-updater] {today} {now} | model={MODEL} | dry_run={args.dry_run}\n")
    with open(args.html,"r",encoding="utf-8") as f: html=f.read()

    all_results={}
    for topic in TOPICS:
        print(f"  [{topic['id'].upper()}] Fetching RSS...")
        items=fetch_feed_items(topic); print(f"           {len(items)} items | Calling Claude...")
        result=analyze_topic(client,topic,items,today); all_results[topic["id"]]=result
        if result:
            html=replace_marker(html,f"card:{topic['id']}",build_card_html(result))
            html=replace_marker(html,f"badge:{topic['id']}",build_badge_html(result))
            print("           ✓ Updated")
        else: print("           ✗ Skipped")

    print("\n  Synthesizing banner + feed...")
    gr=analyze_banner_and_feed(client,all_results,today)
    if gr:
        if "banner_html"  in gr: html=replace_marker(html,"banner",gr["banner_html"])
        if "merged_feed" in gr: html=replace_marker(html,"feed",build_feed_html(gr["merged_feed"]))

    html=replace_marker(html,"timestamp",today); html=replace_marker(html,"refreshtime",now)

    if args.dry_run:
        print("\n[DRY RUN] HTML not written.")
    else:
        with open(args.html,"w",encoding="utf-8") as f: f.write(html)
        print(f"\n  ✓ {args.html} written ({len(html):,} bytes)")

    print("\n  Generating monthly briefing...")
    briefing=generate_briefing(client,all_results,today)
    print(f"  ✓ {len(briefing):,} chars")

    if args.dry_run:
        print("\n[DRY RUN] Briefing preview:\n"+"-"*60+"\n"+briefing[:800]+"\n"+"-"*60+"\n  Email not sent.")
    else:
        print("\n  Sending email...")
        send_briefing_email(briefing,today)

    print("\n[DONE]")

if __name__=="__main__":
    main()
