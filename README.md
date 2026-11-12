# MARS AI Weekly

Standalone AI Weekly Report Generator — extracted from [Mars](https://github.com/UJ2202/MARS.git).

Generates publication-ready AI news reports through a 4-stage pipeline:
1. **Data Collection** — Scrapes RSS feeds, NewsAPI, Google News, DuckDuckGo (no LLM)
2. **Content Curation** — LLM deduplicates and filters collected items
3. **Report Generation** — LLM writes a structured markdown report
4. **Quality Review** — LLM polishes and finalizes the report

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+

### Development

```bash
git clone https://github.com/mars-fabric/MARS-AIWeekly.git

cd MARS-AIWeekly/

cp .env.example .env  # fill in API keys

python -m venv .venv && source .venv/bin/activate

pip install -r Requirements.txt 

# Start backend (port 8000)
cd backend/

python run.py

# In another terminal ( project root) — install and start frontend (port 3022)
cd mars-ui/

cp .env.local.example .env.local

npm install

npm run dev

Open http://localhost:3022

```

### Docker

```bash
docker compose up
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM stages 2-4 |
| `NEWSAPI_KEY` | No | NewsAPI key for expanded data collection |

## Architecture

See the [docs/](docs/) folder for detailed documentation.
