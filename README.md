# GitMesh

GitMesh는 GitHub ID 하나로 사용자의 top 5 recently updated public repository들을 수집하고, Upstage/Solar LLM으로 각 repository의 Project DNA, Reusable Asset Cards, Develop Report를 생성한 뒤, 전체 repository를 Project Knowledge Graph로 시각화하는 웹 서비스입니다.

## 구조

```text
gitmesh_app/
  backend/   FastAPI + GitHub API + Upstage/Solar LLM
  web/       Vanilla HTML/CSS/JS frontend
```

## 실행 순서

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 Upstage API 키를 입력합니다.

```env
GITHUB_TOKEN=
UPSTAGE_API_KEY=your_upstage_api_key
UPSTAGE_MODEL=solar-pro3
UPSTAGE_BASE_URL=https://api.upstage.ai/v1
```

실행:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Web

```bash
cd web
python -m http.server 5173
```

브라우저에서 열기:

```text
http://127.0.0.1:5173
```

## 주요 기능

- GitHub username 기반 top 5 recently updated public repository 수집
- README, description, language, topics, file tree 분석
- Upstage/Solar LLM 기반 Project DNA 생성
- Reusable Asset Cards 생성
- Develop Report 생성
- File Tree Suggestion 생성
- 사용자 전체 repository 기반 Knowledge Graph 시각화
- 프로젝트 노드 클릭 시 상세 리포트 표시
- rule-based fallback 없음: LLM 실패 시 오류 화면 표시
