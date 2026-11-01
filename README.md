# Job Agent

Discover and score jobs against your profile — **no paid APIs**.

## Setup

```bash
git clone https://github.com/aryangoyalag/AI-Job-Scraper.git
cd AI-Job-Scraper

python -m venv venv
venv\Scripts\activate   # macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
streamlit run app.py
```

## Discover (main flow)

1. Set keyword, location, and profile under **Settings & export** → Save.
2. Open **Discover** → **Run discovery**.

Sources (all free):

| Source | Method |
|--------|--------|
| LinkedIn, Indeed, Naukri | JobSpy |
| Google Jobs | Local Playwright + JobSpy HTML parser |
| Short descriptions | Optional Playwright fetch of posting URL |

## Import list

Paste titles + links (or CSV) if you already have an application tracker.

## Notes

- Google may show CAPTCHA — try turning off **Headless browser** in Settings.
- Re-score with checkbox when matcher rules change.
- Experience filter on **Results** hides jobs needing much more YoE than your profile.
- Copy `config.example.json` to `config.json` locally; `config.json` is not committed.

## Autonomous agent layer
Notion human-in-the-loop, resume tailoring and Gmail tracking: see [AGENT.md](AGENT.md).
