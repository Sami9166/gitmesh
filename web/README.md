# GitMesh

**GitMesh**는 GitHub repository 또는 업로드한 프로젝트 파일들을 그래프로 연결하고, 선택한 노드에 대해 AI 분석 리포트를 생성하는 웹 기반 프로젝트 분석 도구입니다.

GitMesh는 **프로젝트의 끝**을 **또다른 시작**으로 바꿔줍니다.

---

## 주요 기능

### 1. GitHub Project Graph

사용자가 GitHub username을 입력하면 최근 업데이트 기준 최대 10개의 public repository를 가져옵니다.

수집한 repository metadata를 바탕으로 Upstage/Solar 모델이 repository 간 관계를 판단하고, Cytoscape.js 기반 그래프로 시각화합니다.

사용 데이터:

- repository name
- description
- primary language
- topics
- stars / forks
- updated_at

그래프 생성 단계에서는 속도와 비용을 줄이기 위해 전체 파일 내용을 읽지 않습니다.

---

### 2. Add Project from File

GitHub가 아니더라도 프로젝트 관련 파일을 업로드해 그래프를 만들 수 있습니다.

지원하는 예시:

- README.md
- 기획서 txt/md
- 코드 파일
- JSON / YAML
- 간단한 문서 파일

업로드한 파일들은 각각 하나의 노드가 되며, Upstage/Solar가 파일 간 관계를 판단합니다.

파일 목록에서는 개별 파일 삭제가 가능합니다.

---

### 3. Node Preview

그래프에서 노드를 클릭하면 preview modal이 열립니다.

GitHub repository 노드에서는 다음 정보를 확인할 수 있습니다.

- repository name
- description
- language
- topics
- stars / forks
- related nodes
- GitHub link
- AI 분석 시작 버튼

파일 노드에서는 다음 정보를 확인할 수 있습니다.

- file name
- file type
- related nodes
- AI 분석 시작 버튼

---

### 4. AI Analysis Report

AI 분석은 사용자가 선택한 노드에 대해서만 실행됩니다.

GitHub repository의 경우:

1. README와 file tree를 가져옵니다.
2. Upstage/Solar가 분석에 필요한 핵심 파일 path를 선택합니다.
3. GitHub Contents API로 선택된 파일 일부를 읽습니다.
4. 선택된 파일 내용과 README를 바탕으로 분석 리포트를 생성합니다.

파일 업로드의 경우:

1. 업로드한 파일 내용을 기반으로 분석합니다.
2. 해당 파일을 프로젝트 산출물로 보고 분석 리포트를 생성합니다.

AI 분석 리포트는 다음 세 가지 섹션으로 구성됩니다.

1. **Asset Card**
2. **Develop Point**
3. **Roadmap**

---

## 기술 스택

### Frontend

- HTML
- CSS
- JavaScript
- Cytoscape.js

### Backend

- Python
- FastAPI
- httpx
- OpenAI-compatible client
- Upstage/Solar API
- GitHub REST API

---

## 프로젝트 구조

```text
gitmesh_app/
  README.md
  .gitignore

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

  web/
    README.md
    index.html
    app.js
    styles.css