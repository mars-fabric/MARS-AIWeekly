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
# Install backend
python -m venv .venv && source .venv/bin/activate
pip install -r Requirements.txt 
# OR pip install -e .

pip install -e ".[data]"       # Optional: scipy, matplotlib, xgboost
pip install -e ".[jupyter]"    # Optional: Jupyter support

# Start backend (port 8000)
cd backend && python run.py

# In another terminal — install and start frontend (port 3000)
cd mars-ui && npm install && npm run dev
```

### Docker

```bash
cp .env.example .env  # fill in API keys
docker compose up
```

Open http://localhost:3000

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM stages 2-4 |
| `NEWSAPI_KEY` | No | NewsAPI key for expanded data collection |

## Architecture

See the [docs/](docs/) folder for detailed documentation.
