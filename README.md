# 🛰️ Fusion Watch Intelligence Tracker

**An autonomous geopolitical monitoring system powered by Claude AI and GitHub Actions.**

[![Workflow](https://img.shields.io/badge/automation-GitHub%20Actions-2088FF?logo=github-actions&logoColor=white)](/.github/workflows/grand-strategy-update.yml)
[![AI](https://img.shields.io/badge/AI-Claude%20Opus%204-8A2BE2)](https://anthropic.com)
[![Deploy](https://img.shields.io/badge/deploy-GitHub%20Pages-222?logo=github)](https://prisonerofazkabanz.github.io/fusion-tracker)
[![License](https://img.shields.io/badge/license-MIT-green)](/LICENSE)

---

## What It Does

Fusion Watch is a fully automated intelligence dashboard that tracks six active geopolitical story threads in real time. Once a month — or on demand — a GitHub Actions pipeline:

1. **Ingests RSS feeds** from Reuters, BBC, Al Jazeera, the New York Times, and the EIA across all six topics
2. **Calls Claude** (Anthropic's frontier model) seven times — once per story thread and once to synthesize a global banner and feed
3. **Injects the analysis** directly into a live HTML dashboard hosted on GitHub Pages using HTML comment markers as injection targets
4. **Generates a full intelligence briefing** document — executive summary, competitor degradation matrix, chokepoint control assessment, forward indicators, and confidence rating
5. **Emails the briefing** to a private inbox via Gmail SMTP, styled to match the dashboard aesthetic

Zero human intervention required after initial setup.

---

## Live Dashboard

**[→ View the live tracker](https://prisonerofazkabanz.github.io/fusion-tracker/grand-strategy.html)**

Updated automatically on the 1st of each month at 06:00 UTC.

---

## Story Threads

| Thread | Focus |
|---|---|
| **Iran Kill Chain** | Regime fragmentation, export blockade status, proxy network activity |
| **Qatar LNG Strike** | Ras Laffan / Mesaieed facility status, global LNG spot prices |
| **Russia Degradation** | Refinery strikes, shadow fleet seizures, export capacity |
| **Venezuela / Americas** | PDVSA transition, Western Hemisphere energy deals |
| **Chokepoint Control** | Malacca, Gibraltar, Hormuz, Panama Canal — US control posture |
| **US Energy Monopoly** | LNG export dominance, Maritime Action Plan, bilateral deals |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  GitHub Actions                     │
│                                                     │
│  Trigger: cron (1st of month) or workflow_dispatch  │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  scripts/update_grand_strategy.py            │   │
│  │                                              │   │
│  │  feedparser → RSS ingestion (6 topics)       │   │
│  │  anthropic  → Claude analysis (7 API calls)  │   │
│  │  re         → HTML marker injection          │   │
│  │  smtplib    → Gmail SMTP briefing email      │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  git commit → main → GitHub Pages (auto-deploy)     │
└─────────────────────────────────────────────────────┘
```

**Stack:**
- Python 3.11
- [Anthropic Python SDK](https://github.com/anthropic-ai/anthropic-sdk-python) — `claude-opus-4-5`
- `feedparser`, `requests`, `beautifulsoup4`
- GitHub Actions (cron + `workflow_dispatch`)
- GitHub Pages
- Gmail SMTP (App Password auth)

---

## How It Works — Technical Details

### HTML Injection via Comment Markers

The dashboard HTML uses paired comment markers as injection targets:

```html
<!-- GS:START:card:iran -->
  ... Claude writes here ...
<!-- GS:END:card:iran -->
```

The Python script uses `re.compile` with `re.DOTALL` to find and replace content between every marker pair. This keeps the HTML template static and human-editable while making every Claude-generated section surgically replaceable.

### Prompt Architecture

Each topic gets a structured prompt containing:
- Story context (what the thread is tracking)
- Filtered RSS items (keyword-matched, deduplicated)
- Badge option map (controls the status indicator CSS class)
- Strict JSON output schema

Claude returns structured JSON for every field — badge class, card summary HTML, three metrics, analysis line, feed items. No parsing ambiguity.

### Dry Run Mode

The workflow exposes a `dry_run` input. When `true`, all Claude calls execute and output is printed to the Actions log — but no file is written and no email is sent. Useful for verifying prompt output quality without side effects.

---

## Setup

### 1. Fork and configure secrets

Add these to **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GMAIL_ADDRESS` | Gmail address used as sender |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your account password) |
| `BRIEFING_TO_EMAIL` | Where the monthly briefing is delivered |

### 2. Enable GitHub Pages

Settings → Pages → Source: **Deploy from a branch** → `main` → `/ (root)`

### 3. Add GS marker pairs to your HTML

Ensure `grand-strategy.html` contains the expected `GS:START` / `GS:END` comment pairs for each topic ID and the global `banner`, `feed`, `timestamp`, and `refreshtime` markers.

### 4. Run it

Trigger manually via **Actions → Grand Strategy Monthly Update → Run workflow**, or wait for the cron to fire on the 1st.

---

## Project Structure

```
fusion-tracker/
├── grand-strategy.html              # Live dashboard (auto-updated)
├── scripts/
│   ├── update_grand_strategy.py    # Core automation script
│   └── requirements.txt            # Python dependencies
└── .github/
    └── workflows/
        └── grand-strategy-update.yml
```

---

## Philosophy

Most geopolitical dashboards are either manually updated (stale within days) or aggregators that surface raw headlines without synthesis. This project explores a middle path: using a large language model not to generate opinion, but to perform structured analytical compression — taking 50 RSS items and producing the three metrics, one status badge, and two sentences that actually matter.

The goal is a dashboard you can open once a month and immediately understand the state of six complex story threads without reading anything else.

---

## License

MIT
