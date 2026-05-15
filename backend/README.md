# GitMesh Backend

FastAPI backend for GitHub repository collection and Upstage/Solar LLM-based GitMesh analysis.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Required:

```env
UPSTAGE_API_KEY=your_upstage_api_key
UPSTAGE_MODEL=solar-pro3
UPSTAGE_BASE_URL=https://api.upstage.ai/v1
```

Optional:

```env
GITHUB_TOKEN=your_github_token_for_higher_rate_limit
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

```text
GET  /health
POST /github/analyze-user?username=<github_id>&limit=12
GET  /github/{username}/repos?limit=20
```

No rule-based fallback is used. If Upstage fails, the API returns an error response and the web app shows an error page.
