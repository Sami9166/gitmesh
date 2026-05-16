# GitMesh Backend

GitMesh Backend는 FastAPI 기반 서버입니다.

역할은 다음과 같습니다.

1. GitHub public repository 수집
2. 업로드 파일 수집
3. Upstage/Solar API를 통한 graph 생성
4. 선택한 repository 또는 파일에 대한 AI 분석
5. frontend에 graph와 report JSON 제공

---

## 기술 스택

- Python
- FastAPI
- Pydantic
- httpx
- python-dotenv
- OpenAI-compatible client
- Upstage/Solar API
- GitHub REST API

---

## 폴더 구조

```text
backend/
  README.md
  requirements.txt
  .env.example

  app/
    __init__.py
    main.py
    github_client.py
    llm_analyzer.py
    models.py