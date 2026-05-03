# jeffry.running

Personal running log. One-way broadcast. No leaderboards.

## Stack

- **Astro** — static site generator
- **GitHub Pages** — free hosting, custom domain
- **GitHub Actions** — nightly sync + deploy at 05:00 UTC
- **Tredict API** — activity data source (Suunto → Tredict → here)

## Setup

### 1. Create GitHub repo

```bash
git init
git remote add origin git@github.com:yourusername/jeffry-running.git
git push -u origin main
```

### 2. Enable GitHub Pages

GitHub repo → Settings → Pages → Source: **GitHub Actions**

### 3. Add secrets

GitHub repo → Settings → Secrets → Actions:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TREDICT_API_KEY` | Your Tredict API key (Settings → API in Tredict) |

### 4. Custom domain

GitHub repo → Settings → Pages → Custom domain: `jeffry.running`

Add DNS records at your registrar:
```
CNAME  jeffry.running  yourusername.github.io
```

### 5. Install and run locally

```bash
npm install
npm run dev
```

### 6. Trigger first sync manually

GitHub repo → Actions → Sync & Deploy → Run workflow

## Data flow

```
Suunto watch
    ↓ auto-sync
Tredict
    ↓ REST API (nightly GitHub Action)
data/activities.json
    ↓ Astro build
dist/ → GitHub Pages → jeffry.running
```

## Adding notes to a run

Open `data/activities.json`, find the activity by date, add a `"note"` field:

```json
{
  "id": "...",
  "date": "2026-05-03T...",
  "note": "First time on the Nete loop. Good legs."
}
```

Commit and push — site rebuilds automatically via GitHub Actions.

## Project structure

```
jeffry-running/
├── .github/workflows/sync-deploy.yml   # Nightly sync + deploy
├── scripts/sync.py                     # Tredict → activities.json
├── data/activities.json                # Activity data (committed)
├── src/
│   ├── layouts/Base.astro              # Shared HTML shell + CSS
│   ├── pages/
│   │   ├── index.astro                 # Run log index
│   │   ├── about.astro                 # About page
│   │   └── run/[id].astro              # Individual run detail
└── package.json
```
