# GitMesh Web

GitMesh Web은 GitMesh의 프론트엔드입니다.

사용자는 웹 화면에서 GitHub username을 입력하거나 프로젝트 파일을 업로드해 프로젝트 그래프를 생성할 수 있습니다. 그래프의 노드를 클릭하면 preview modal이 열리고, 선택한 노드에 대해 AI 분석을 실행할 수 있습니다.

AI 분석 결과는 별도 report page에서 확인합니다.

---

## 주요 기능

### 1. GitHub Graph 생성

GitHub username을 입력하면 backend의 `/github/scan-user` API를 호출합니다.

```text
GitHub username 입력
→ backend API 호출
→ GitHub public repository 최대 10개 수집
→ Upstage/Solar 기반 repo 관계 graph 생성
→ Cytoscape.js로 graph 시각화
```

---

### 2. Add Project from File

파일 업로드 기능을 제공합니다.

사용자는 프로젝트 관련 파일을 여러 개 업로드할 수 있고, 업로드한 파일은 각각 graph node로 표시됩니다.

지원 예시:

- README.md
- txt / md 문서
- 코드 파일
- JSON / YAML
- 간단한 기획 문서

업로드 후 파일 목록에서 개별 파일을 삭제할 수 있습니다.

---

### 3. Graph Visualization

그래프는 Cytoscape.js로 시각화합니다.

지원 기능:

- node drag
- zoom
- pan
- fit graph
- node click
- selected node highlight
- related edge highlight

현재 layout은 `concentric` 기반입니다.

연결이 많은 노드가 중심에 배치되고, 연결이 적은 노드는 바깥쪽으로 배치됩니다.

---

### 4. Node Preview Modal

그래프 노드를 클릭하면 preview modal이 열립니다.

GitHub repository 노드에서는 다음 정보를 보여줍니다.

- repository name
- description
- language
- topics
- stars
- forks
- related nodes
- GitHub link
- AI 분석 시작 버튼

파일 노드에서는 다음 정보를 보여줍니다.

- file name
- file type
- related nodes
- AI 분석 시작 버튼

---

### 5. AI Analysis Report

AI 분석은 선택한 노드에 대해서만 실행됩니다.

분석 결과는 별도 report page에서 보여줍니다.

리포트는 세 개의 섹션으로 구성됩니다.

1. Asset Card
2. Develop Point
3. Roadmap

---

### 6. Theme

Light mode와 Dark mode를 지원합니다.

테마 선택값은 `localStorage`에 저장됩니다.

```text
GITMESH_THEME=light
GITMESH_THEME=dark
```

처음 접속 시에는 브라우저 시스템 테마를 따릅니다.

---

## 파일 구조

```text
web/
  README.md
  index.html
  app.js
  styles.css
```
