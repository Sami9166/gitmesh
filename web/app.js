const API_BASE_URL =
  localStorage.getItem("GITMESH_API_BASE_URL") || "http://127.0.0.1:8000";

const state = {
  view: "home", // home | loading | result | report | error
  sourceMode: "github", // github | files
  username: "",
  scanId: null,
  limit: 10,
  response: null,
  selectedProjectId: null,
  previewProjectId: null,
  analyzingProjectId: null,
  analysisByProjectId: {},
  analysisErrorByProjectId: {},
  uploadedFiles: [],
  error: null,
};

const app = document.getElementById("app");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function truncate(value, length = 20) {
  const text = String(value || "");
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function shell(content) {
  return `
    <main class="shell">
      <nav class="nav">
        <div class="brand">
          <div class="logo">GM</div>
          <span>GitMesh</span>
        </div>
        <div class="nav-pill">GitHub & File Project Graph</div>
      </nav>
      ${content}
    </main>
  `;
}

function renderHome() {
  app.innerHTML = shell(`
    <section class="hero">
      <div class="card hero-card">
        <div class="eyebrow">GitHub 또는 파일로 시작</div>
        <h1>흩어진 repo와 파일을<br />다음 빌드의 자산으로.</h1>
        <p class="subtitle">
          GitMesh는 GitHub public repository 최대 10개 또는 업로드한 파일들을 그래프로 연결하고,
          관심 있는 노드만 선택해 AI 분석 리포트를 생성합니다.
        </p>

        <div class="mode-tabs">
          <button id="mode-github" class="mode-tab active">GitHub Graph</button>
          <button id="mode-files" class="mode-tab">Add Project from File</button>
        </div>

        <form id="github-form" class="input-row">
          <input
            id="username"
            class="github-input"
            name="username"
            placeholder="GitHub username 입력 예: octocat"
            autocomplete="off"
          />
          <button class="primary-btn" type="submit">그래프 생성</button>
        </form>

        <form id="file-form" class="file-form hidden">
          <label class="file-drop">
            <input id="project-files" type="file" multiple />
            <div class="file-drop-title">프로젝트 파일 업로드</div>
            <div class="file-drop-desc">
              README, 기획서 txt/md, 코드 파일, json/yaml 등을 여러 개 올리면 파일 간 graph를 생성합니다.
            </div>
          </label>
          <button class="primary-btn" type="submit">파일 그래프 생성</button>
          <div id="file-list" class="file-list"></div>
        </form>

        <div class="sample-row">
          <button class="sample-chip" data-sample="octocat">octocat</button>
          <button class="sample-chip" data-sample="torvalds">torvalds</button>
          <button class="sample-chip" data-sample="gaearon">gaearon</button>
        </div>
      </div>

      <div class="card preview-card">
        <div class="preview-title">GitMesh Flow</div>
        <div class="mini-grid">
          <div class="mini-card"><div class="mini-label">Step 1</div><div class="mini-value">Graph First</div></div>
          <div class="mini-card"><div class="mini-label">Step 2</div><div class="mini-value">Node Preview</div></div>
          <div class="mini-card"><div class="mini-label">Step 3</div><div class="mini-value">AI Analysis</div></div>
          <div class="mini-card"><div class="mini-label">Step 4</div><div class="mini-value">Report Page</div></div>
        </div>
        <div class="flow-box">
          GitHub ID 또는 파일 업로드<br />
          → Upstage가 관계 graph 생성<br />
          → 노드 클릭 시 preview modal<br />
          → AI 분석 후 별도 report page에서 확인
        </div>
      </div>
    </section>
  `);

  const githubForm = document.getElementById("github-form");
  const fileForm = document.getElementById("file-form");
  const modeGithub = document.getElementById("mode-github");
  const modeFiles = document.getElementById("mode-files");
  const fileInput = document.getElementById("project-files");
  const fileList = document.getElementById("file-list");

  function renderSelectedFiles() {
    if (!state.uploadedFiles.length) {
      fileList.innerHTML = `<div class="file-empty">선택된 파일이 없습니다.</div>`;
      return;
    }

    fileList.innerHTML = state.uploadedFiles
      .map((file, index) => `
        <span class="file-chip" title="${escapeHtml(file.name)}">
          <span class="file-chip-name">${escapeHtml(file.name)}</span>
          <button
            type="button"
            class="file-remove"
            data-file-index="${index}"
            aria-label="${escapeHtml(file.name)} 삭제"
          >×</button>
        </span>
      `)
      .join("");

    fileList.querySelectorAll("[data-file-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.fileIndex);
        state.uploadedFiles.splice(index, 1);
        fileInput.value = "";
        renderSelectedFiles();
      });
    });
  }

  function addFiles(files) {
    const existing = new Set(
      state.uploadedFiles.map((file) => `${file.name}::${file.size}::${file.lastModified}`)
    );

    for (const file of files) {
      const key = `${file.name}::${file.size}::${file.lastModified}`;
      if (existing.has(key)) continue;
      if (state.uploadedFiles.length >= 20) break;
      state.uploadedFiles.push(file);
      existing.add(key);
    }

    renderSelectedFiles();
  }

  function setMode(mode) {
    state.sourceMode = mode;
    modeGithub.classList.toggle("active", mode === "github");
    modeFiles.classList.toggle("active", mode === "files");
    githubForm.classList.toggle("hidden", mode !== "github");
    fileForm.classList.toggle("hidden", mode !== "files");
  }

  modeGithub.addEventListener("click", () => setMode("github"));
  modeFiles.addEventListener("click", () => setMode("files"));

  githubForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = document.getElementById("username").value.trim();
    if (!username) return;
    await scanUser(username);
  });

  fileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.uploadedFiles.length) return;
    await scanFiles([...state.uploadedFiles]);
  });

  fileInput.addEventListener("change", () => {
    addFiles(Array.from(fileInput.files || []));
    fileInput.value = "";
  });

  renderSelectedFiles();

  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", () => {
      setMode("github");
      document.getElementById("username").value = button.dataset.sample;
    });
  });
}

function renderLoading() {
  const text = state.sourceMode === "files"
    ? "업로드한 파일들의 관계 그래프를 만들고 있어요"
    : "GitHub 프로젝트 그래프를 만들고 있어요";
  const sub = state.sourceMode === "files"
    ? "파일 내용 일부를 기반으로 Upstage/Solar가 파일 간 관계를 판단하는 중입니다."
    : "최근 업데이트 기준 최대 10개 repository의 metadata를 수집하고 Upstage/Solar가 repo 간 관계를 판단하는 중입니다.";
  app.innerHTML = shell(`
    <section class="loading-page">
      <div class="card loading-card">
        <div class="spinner"></div>
        <h2>${escapeHtml(text)}</h2>
        <p class="muted">${escapeHtml(sub)}</p>
      </div>
    </section>
  `);
}

function normalizeError(error) {
  if (!error) return { title: "알 수 없는 오류", message: "분석 중 문제가 발생했습니다." };
  if (typeof error === "string") return { title: "분석 실패", message: error };
  if (error.title || error.message) {
    return { title: error.title || "분석 실패", message: error.message || "요청을 처리하지 못했습니다." };
  }
  return { title: "분석 실패", message: JSON.stringify(error) };
}

function renderError() {
  const error = normalizeError(state.error);
  app.innerHTML = shell(`
    <section class="error-page">
      <div class="card error-card">
        <div class="error-icon">!</div>
        <div class="error-title">${escapeHtml(error.title)}</div>
        <div class="error-message">${escapeHtml(error.message)}</div>
        <button id="retry" class="primary-btn">다시 시도</button>
      </div>
    </section>
  `);
  document.getElementById("retry").addEventListener("click", () => {
    state.view = "home";
    state.error = null;
    render();
  });
}

async function scanUser(username) {
  state.sourceMode = "github";
  state.username = username;
  state.scanId = null;
  state.view = "loading";
  state.error = null;
  state.response = null;
  state.selectedProjectId = null;
  state.previewProjectId = null;
  state.analysisByProjectId = {};
  state.analysisErrorByProjectId = {};
  render();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 180000);
  try {
    const url = `${API_BASE_URL}/github/scan-user?username=${encodeURIComponent(username)}&limit=${state.limit}`;
    const res = await fetch(url, { method: "POST", signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw body.detail || body || `HTTP ${res.status}`;
    state.response = body;
    state.selectedProjectId = body.projects?.[0]?.project_id || null;
    state.previewProjectId = null;
    state.view = "result";
    render();
  } catch (error) {
    state.error = error?.name === "AbortError"
      ? { title: "그래프 생성 시간이 너무 오래 걸립니다", message: "GitHub 또는 Upstage 응답이 지연되고 있습니다." }
      : error;
    state.view = "error";
    render();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function scanFiles(files) {
  state.sourceMode = "files";
  state.username = "uploaded-files";
  state.scanId = null;
  state.view = "loading";
  state.error = null;
  state.response = null;
  state.selectedProjectId = null;
  state.previewProjectId = null;
  state.analysisByProjectId = {};
  state.analysisErrorByProjectId = {};
  render();

  const formData = new FormData();
  files.slice(0, 20).forEach((file) => formData.append("files", file));
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 180000);
  try {
    const res = await fetch(`${API_BASE_URL}/files/scan-project`, { method: "POST", body: formData, signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw body.detail || body || `HTTP ${res.status}`;
    state.response = body;
    state.scanId = body.scan_id;
    state.selectedProjectId = body.projects?.[0]?.project_id || null;
    state.previewProjectId = null;
    state.view = "result";
    render();
  } catch (error) {
    state.error = error?.name === "AbortError"
      ? { title: "파일 그래프 생성 시간이 너무 오래 걸립니다", message: "파일 수가 많거나 Upstage 응답이 지연되고 있습니다." }
      : error;
    state.view = "error";
    render();
  } finally {
    clearTimeout(timeoutId);
  }
}

function projectById(id) {
  return state.response?.projects?.find((project) => project.project_id === id) || null;
}

function makeProjectNetwork() {
  const projects = state.response?.projects || [];
  const projectIds = new Set(projects.map((project) => project.project_id));
  const edges = [];
  const seen = new Set();

  for (const project of projects) {
    for (const target of project.related_project_ids || []) {
      if (!projectIds.has(target)) continue;
      const key = [project.project_id, target].sort().join("::");
      if (!seen.has(key)) {
        seen.add(key);
        edges.push({ source: project.project_id, target, relation: "related" });
      }
    }
  }

  for (const edge of state.response?.graph?.edges || []) {
    if (projectIds.has(edge.source) && projectIds.has(edge.target)) {
      const key = [edge.source, edge.target].sort().join("::");
      if (!seen.has(key)) {
        seen.add(key);
        edges.push(edge);
      }
    }
  }
  return { nodes: projects, edges };
}

function renderProjectGraph() {
  const nodeLabel = state.sourceMode === "files" ? "uploaded file" : "GitHub repository";

  return `
    <div class="graph-toolbar">
      <div class="graph-help">
        <b>Tip</b>
        노드를 드래그하거나 확대/축소할 수 있습니다. 노드를 클릭하면 preview가 열립니다.
      </div>
      <button id="fit-graph" class="secondary-btn small-btn">그래프 맞춤</button>
    </div>

    <div id="cy" class="cy-graph" aria-label="Project knowledge graph"></div>

    <div class="legend">
      <span>노드: ${nodeLabel}</span>
      <span>선: 유사성·재사용·협업 가능성</span>
      <span>클릭: preview</span>
      <span>드래그: 위치 조정</span>
    </div>
  `;
}

function relationLabel(relation) {
  const labels = {
    related: "관련",
    similar_to: "유사",
    shares_domain_with: "도메인 공유",
    shares_tech_with: "기술 공유",
    can_collaborate_with: "협업 가능",
    can_reuse_asset_from: "재사용",
    can_improve_with: "개선 가능",
    same_project: "같은 프로젝트",
    depends_on: "의존",
    complements: "보완",
    can_be_combined_with: "결합 가능",
    improves: "개선",
  };

  return labels[relation] || relation || "관련";
}

function nodeColor(project) {
  const language = String(project.repo?.primary_language || "").toLowerCase();

  if (state.sourceMode === "files") return "#7c3aed";
  if (language.includes("python")) return "#3182f6";
  if (language.includes("javascript")) return "#f59e0b";
  if (language.includes("typescript")) return "#2563eb";
  if (language.includes("dart")) return "#06b6d4";
  if (language.includes("java")) return "#ef4444";
  if (language.includes("html") || language.includes("css")) return "#10b981";

  return "#64748b";
}

function buildCytoscapeElements() {
  const { nodes, edges } = makeProjectNetwork();

  const cyNodes = nodes.map((project) => ({
    group: "nodes",
    data: {
      id: project.project_id,
      label: truncate(project.repo?.name || project.project_id, 18),
      sublabel: state.sourceMode === "files" ? "File" : project.repo?.primary_language || "Repo",
      color: nodeColor(project),
      type: state.sourceMode === "files" ? "file" : "repo",
    },
  }));

  const cyEdges = edges.map((edge, index) => ({
    group: "edges",
    data: {
      id: `edge_${index}_${edge.source}_${edge.target}`,
      source: edge.source,
      target: edge.target,
      label: relationLabel(edge.relation),
      weight: edge.weight || 0.5,
      relation: edge.relation || "related",
    },
  }));

  return [...cyNodes, ...cyEdges];
}

function mountCytoscapeGraph() {
  const container = document.getElementById("cy");
  if (!container) return;

  if (!window.cytoscape) {
    container.innerHTML = `
      <div class="empty-state">
        Cytoscape.js를 불러오지 못했습니다. index.html의 script 태그를 확인해주세요.
      </div>
    `;
    return;
  }

  const elements = buildCytoscapeElements();

  const cy = cytoscape({
    container,
    elements,
    wheelSensitivity: 0.18,
    minZoom: 0.35,
    maxZoom: 2.2,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          label: "data(label)",
          "text-valign": "center",
          "text-halign": "center",
          color: "#ffffff",
          "font-size": 12,
          "font-weight": 800,
          "text-outline-width": 2,
          "text-outline-color": "data(color)",
          width: 78,
          height: 78,
          "border-width": 4,
          "border-color": "#ffffff",
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-width": 6,
          "border-color": "#111827",
        },
      },
      {
        selector: "edge",
        style: {
          width: "mapData(weight, 0, 1, 1.5, 5)",
          "line-color": "#cbd5e1",
          "target-arrow-color": "#cbd5e1",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          label: "",
          "font-size": 10,
          color: "#64748b",
          "text-background-color": "#ffffff",
          "text-background-opacity": 0.82,
          "text-background-padding": 3,
          "text-rotation": "autorotate",
        },
      },
      {
        selector: "edge.active",
        style: {
          "line-color": "#3182f6",
          "target-arrow-color": "#3182f6",
          width: 5,
          color: "#1b64da",
        },
      },
      {
        selector: ".faded",
        style: {
          opacity: 0.18,
        },
      },
    ],
    layout: {
      name: "concentric",
      fit: true,
      padding: 70,
      animate: true,
      animationDuration: 600,
      minNodeSpacing: 70,
      concentric: function (node) {
        return node.degree();
      },
      levelWidth: function () {
        return 1;
      },
    },
  });

  cy.on("tap", "node", (event) => {
    const projectId = event.target.id();
    state.selectedProjectId = projectId;
    state.previewProjectId = projectId;

    cy.elements().removeClass("faded active");
    const selected = cy.$id(projectId);
    const neighborhood = selected.closedNeighborhood();

    cy.elements().not(neighborhood).addClass("faded");
    selected.connectedEdges().addClass("active");

    renderResult();
  });

  cy.on("mouseover", "node", (event) => {
    container.style.cursor = "pointer";
    event.target.animate({ style: { width: 88, height: 88 } }, { duration: 120 });
  });

  cy.on("mouseout", "node", (event) => {
    container.style.cursor = "default";
    event.target.animate({ style: { width: 78, height: 78 } }, { duration: 120 });
  });

  const fitButton = document.getElementById("fit-graph");
  if (fitButton) {
    fitButton.addEventListener("click", () => cy.fit(undefined, 48));
  }

  setTimeout(() => cy.fit(undefined, 48), 50);
}

function listItems(items) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return `<div class="empty-state">아직 분석된 항목이 없습니다.</div>`;
  return `<ul class="ul">${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function tagList(items) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return `<span class="tag">None</span>`;
  return values.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("");
}

function getRelatedProjectNames(project) {
  return (project.related_project_ids || []).map((id) => projectById(id)?.repo?.name || id).filter(Boolean);
}

function renderRepoPreviewModal(project) {
  if (!project) return "";
  const repo = project.repo || {};
  const analyzed = state.analysisByProjectId[project.project_id];
  const isAnalyzing = state.analyzingProjectId === project.project_id;
  const analysisError = state.analysisErrorByProjectId[project.project_id];
  const related = getRelatedProjectNames(project);
  const isFile = state.sourceMode === "files";

  return `
    <div class="modal-backdrop" id="modal-backdrop">
      <section class="repo-modal card">
        <button class="modal-close" id="modal-close" aria-label="close">×</button>
        <div class="modal-kicker">${isFile ? "File Preview" : "Repository Preview"}</div>
        <h2 class="modal-title">${escapeHtml(repo.name || project.project_id)}</h2>
        <p class="modal-desc">${escapeHtml(repo.description || "No description.")}</p>
        <div class="repo-meta-grid">
          <div class="repo-meta-item"><div class="repo-meta-label">${isFile ? "File Name" : "Full Name"}</div><div class="repo-meta-value">${escapeHtml(repo.full_name || "-")}</div></div>
          <div class="repo-meta-item"><div class="repo-meta-label">Type</div><div class="repo-meta-value">${escapeHtml(repo.primary_language || (isFile ? "File" : "-"))}</div></div>
          <div class="repo-meta-item"><div class="repo-meta-label">Stars</div><div class="repo-meta-value">${isFile ? "-" : escapeHtml(repo.stars ?? 0)}</div></div>
          <div class="repo-meta-item"><div class="repo-meta-label">Forks</div><div class="repo-meta-value">${isFile ? "-" : escapeHtml(repo.forks ?? 0)}</div></div>
        </div>
        <div class="modal-section"><div class="modal-section-title">Topics</div><div class="tags">${tagList(repo.topics)}</div></div>
        <div class="modal-section"><div class="modal-section-title">Related Nodes</div><div class="tags">${tagList(related)}</div></div>
        ${analysisError ? `<div class="inline-error"><b>${escapeHtml(normalizeError(analysisError).title)}</b><p>${escapeHtml(normalizeError(analysisError).message)}</p></div>` : ""}
        <div class="modal-actions">
          ${!isFile ? `<a class="secondary-btn link-btn" href="${escapeHtml(repo.html_url || "#")}" target="_blank" rel="noreferrer">GitHub 열기</a>` : ""}
          ${analyzed ? `<button id="open-report" class="primary-btn">분석 리포트 보기</button>` : `<button id="analyze-repo" class="primary-btn" ${isAnalyzing ? "disabled" : ""}>${isAnalyzing ? "AI 분석 중..." : "AI 분석 시작"}</button>`}
        </div>
      </section>
    </div>
  `;
}

function renderResult() {
  const projects = state.response?.projects || [];
  const selected = projectById(state.selectedProjectId) || projects[0] || null;
  const previewProject = projectById(state.previewProjectId);
  if (selected && selected.project_id !== state.selectedProjectId) state.selectedProjectId = selected.project_id;

  const title = state.sourceMode === "files" ? "Uploaded File Graph" : `${state.response?.username || state.username}의 GitMesh Graph`;
  const desc = state.sourceMode === "files" ? `${projects.length}개 업로드 파일을 그래프로 연결했습니다.` : `최근 업데이트 기준 ${projects.length}개 public repository를 그래프로 연결했습니다.`;

  app.innerHTML = shell(`
    <section class="graph-page">
      <div class="graph-header"><div><div class="section-title">${escapeHtml(title)}</div><div class="muted">${escapeHtml(desc)}</div></div><button id="new-search" class="secondary-btn">새로 시작</button></div>
      <div class="card graph-panel">${renderProjectGraph()}</div>
      ${renderRepoPreviewModal(previewProject)}
    </section>
  `);

  mountCytoscapeGraph();

  document.getElementById("new-search").addEventListener("click", () => {
    state.view = "home";
    state.response = null;
    state.selectedProjectId = null;
    state.previewProjectId = null;
    state.scanId = null;
    render();
  });

  const closeButton = document.getElementById("modal-close");
  if (closeButton) closeButton.addEventListener("click", () => { state.previewProjectId = null; renderResult(); });
  const backdrop = document.getElementById("modal-backdrop");
  if (backdrop) backdrop.addEventListener("click", (event) => { if (event.target.id === "modal-backdrop") { state.previewProjectId = null; renderResult(); } });
  const analyzeButton = document.getElementById("analyze-repo");
  if (analyzeButton && previewProject) analyzeButton.addEventListener("click", () => analyzeSelectedNode(previewProject, { goToReport: true }));
  const reportButton = document.getElementById("open-report");
  if (reportButton && previewProject) reportButton.addEventListener("click", () => { state.selectedProjectId = previewProject.project_id; state.view = "report"; state.previewProjectId = null; render(); });
}

async function analyzeSelectedNode(project, options = {}) {
  if (!project) return;
  if (state.sourceMode === "files") return analyzeSelectedFile(project, options);
  return analyzeSelectedRepo(project, options);
}

async function analyzeSelectedRepo(project, options = {}) {
  if (!project?.repo?.full_name) return;
  const projectId = project.project_id;
  state.analyzingProjectId = projectId;
  state.analysisErrorByProjectId[projectId] = null;
  renderResult();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 210000);
  try {
    const url = `${API_BASE_URL}/github/analyze-repo?full_name=${encodeURIComponent(project.repo.full_name)}`;
    const res = await fetch(url, { method: "POST", signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw body.detail || body || `HTTP ${res.status}`;
    state.analysisByProjectId[projectId] = body.project;
    if (options.goToReport) {
      state.selectedProjectId = projectId;
      state.previewProjectId = null;
      state.view = "report";
      render();
    } else renderResult();
  } catch (error) {
    state.analysisErrorByProjectId[projectId] = error?.name === "AbortError" ? { title: "AI 분석 시간이 너무 오래 걸립니다", message: "해당 repo 분석이 지연되고 있습니다." } : error;
    renderResult();
  } finally {
    state.analyzingProjectId = null;
    clearTimeout(timeoutId);
  }
}

async function analyzeSelectedFile(project, options = {}) {
  if (!state.scanId || !project?.project_id) return;
  const fileId = project.project_id.replace(/^file_/, "");
  const projectId = project.project_id;
  state.analyzingProjectId = projectId;
  state.analysisErrorByProjectId[projectId] = null;
  renderResult();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 210000);
  try {
    const url = `${API_BASE_URL}/files/analyze-file?scan_id=${encodeURIComponent(state.scanId)}&file_id=${encodeURIComponent(fileId)}`;
    const res = await fetch(url, { method: "POST", signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw body.detail || body || `HTTP ${res.status}`;
    state.analysisByProjectId[projectId] = body.project;
    if (options.goToReport) {
      state.selectedProjectId = projectId;
      state.previewProjectId = null;
      state.view = "report";
      render();
    } else renderResult();
  } catch (error) {
    state.analysisErrorByProjectId[projectId] = error?.name === "AbortError" ? { title: "파일 AI 분석 시간이 너무 오래 걸립니다", message: "해당 파일 분석이 지연되고 있습니다." } : error;
    renderResult();
  } finally {
    state.analyzingProjectId = null;
    clearTimeout(timeoutId);
  }
}

function renderReportPage() {
  const projectId = state.selectedProjectId;
  const preview = projectById(projectId);
  const analyzed = state.analysisByProjectId[projectId];
  if (!preview) { state.view = "result"; render(); return; }

  if (!analyzed) {
    app.innerHTML = shell(`
      <section class="report-page">
        <div class="report-topbar"><button id="back-to-graph" class="secondary-btn">← 그래프로 돌아가기</button></div>
        <div class="card report-empty"><h2>아직 분석 결과가 없습니다</h2><p class="muted">${escapeHtml(preview.repo?.name || "선택한 노드")}의 AI 분석을 먼저 실행해주세요.</p><button id="start-analysis" class="primary-btn">AI 분석 시작</button></div>
      </section>
    `);
    document.getElementById("back-to-graph").addEventListener("click", () => { state.view = "result"; render(); });
    document.getElementById("start-analysis").addEventListener("click", () => analyzeSelectedNode(preview, { goToReport: true }));
    return;
  }

  const repo = analyzed.repo || preview.repo || {};
  const dna = analyzed.dna || {};
  const report = analyzed.report || {};
  const selectedFiles = analyzed.selected_files || [];

  app.innerHTML = shell(`
    <section class="report-page">
      <div class="report-topbar">
        <button id="back-to-graph" class="secondary-btn">← 그래프로 돌아가기</button>
        ${state.sourceMode !== "files" ? `<a class="secondary-btn link-btn" href="${escapeHtml(repo.html_url || "#")}" target="_blank" rel="noreferrer">GitHub 열기</a>` : ""}
      </div>
      <header class="report-hero card"><div class="report-kicker">AI Project Report</div><h1>${escapeHtml(repo.name || preview.project_id)}</h1><p>${escapeHtml(dna.summary || repo.description || "Analysis report.")}</p><div class="report-tags">${tagList(dna.domain)}${tagList(dna.tech_stack?.length ? dna.tech_stack : repo.languages)}</div></header>
      <section class="report-grid">
        <div class="card report-card-large"><h2>Project DNA</h2><div class="info-list"><div class="info-row"><div class="info-key">Target User</div><div class="info-value">${escapeHtml(dna.target_user || "Unknown")}</div></div><div class="info-row"><div class="info-key">Core Problem</div><div class="info-value">${escapeHtml(dna.core_problem || "Unknown")}</div></div><div class="info-row"><div class="info-key">Core Features</div><div class="info-value tags">${tagList(dna.core_features)}</div></div><div class="info-row"><div class="info-key">Tech Stack</div><div class="info-value tags">${tagList(dna.tech_stack?.length ? dna.tech_stack : repo.languages)}</div></div></div></div>
        <div class="card report-card-large"><h2>Develop Report</h2><div class="report-subcard"><b>Limitations</b>${listItems(report.limitations)}</div><div class="report-subcard"><b>Develop Points</b>${listItems(report.develop_points)}</div><div class="report-subcard"><b>Keep</b>${listItems(report.keep)}</div><div class="report-subcard"><b>Modify</b>${listItems(report.modify)}</div><div class="report-subcard"><b>Drop</b>${listItems(report.drop)}</div></div>
      </section>
      <section class="report-section"><h2>Reusable Asset Cards</h2><div class="asset-grid">${(analyzed.assets || []).map((asset) => `<div class="card asset-card"><div class="asset-top"><div><div class="asset-name">${escapeHtml(asset.name)}</div><div class="asset-type">${escapeHtml(asset.type)}</div></div><div class="score">reuse ${Math.round((asset.reuse_score || 0) * 100)}%</div></div><div class="asset-block"><b>활용 가능</b>${listItems(asset.reusable_for)}</div><div class="asset-block"><b>보완 필요</b>${listItems(asset.improvement_needed)}</div></div>`).join("") || `<div class="empty-state">Asset Card가 없습니다.</div>`}</div></section>
      <section class="report-grid"><div class="card report-card-large"><h2>${state.sourceMode === "files" ? "Source File" : "Selected Core Files"}</h2>${selectedFiles.length ? selectedFiles.map((file) => `<div class="file-card"><div class="file-path">${escapeHtml(file.path)}</div><div class="file-reason">${escapeHtml(file.reason || "Selected for analysis.")}</div></div>`).join("") : `<div class="empty-state">선택된 핵심 파일 정보가 없습니다.</div>`}</div><div class="card report-card-large"><h2>Structure Suggestion</h2>${listItems(report.file_tree_suggestion)}<h2 style="margin-top: 28px;">Next Build</h2>${listItems(report.next_builds)}</div></section>
    </section>
  `);
  document.getElementById("back-to-graph").addEventListener("click", () => { state.view = "result"; render(); });
}

function render() {
  if (state.view === "loading") return renderLoading();
  if (state.view === "error") return renderError();
  if (state.view === "result") return renderResult();
  if (state.view === "report") return renderReportPage();
  return renderHome();
}

render();
