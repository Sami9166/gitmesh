const API_BASE_URL = localStorage.getItem("GITMESH_API_BASE_URL") || "http://127.0.0.1:8000";

const state = {
  view: "home",
  username: "",
  limit: 5,
  response: null,
  selectedProjectId: null,
  error: null,
  analysisByProjectId: {},
  analyzingProjectId: null,
  analysisErrorByProjectId: {},
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
        <div class="brand"><div class="logo">GM</div><span>GitMesh</span></div>
        <div class="nav-pill">GitHub Project Knowledge Graph</div>
      </nav>
      ${content}
    </main>
  `;
}

function renderHome() {
  app.innerHTML = shell(`
    <section class="hero">
      <div class="card hero-card">
        <div class="eyebrow">GitHub ID 하나로 시작</div>
        <h1>흩어진 repo를<br />다음 빌드의 자산으로.</h1>
        <p class="subtitle">
          GitMesh는 최근 업데이트 기준 상위 5개 public repository를 빠르게 읽고,
          Upstage/Solar LLM으로 repo 관계 그래프를 먼저 생성합니다.
          깊은 Project DNA와 Asset Card는 원하는 repo에서만 선택적으로 분석합니다.
        </p>
        <form id="github-form" class="input-row">
          <input id="username" class="github-input" name="username" placeholder="GitHub username 입력 예: octocat" autocomplete="off" />
          <button class="primary-btn" type="submit">그래프 생성</button>
        </form>
        <div class="sample-row">
          <button class="sample-chip" data-sample="octocat">octocat</button>
          <button class="sample-chip" data-sample="torvalds">torvalds</button>
          <button class="sample-chip" data-sample="gaearon">gaearon</button>
        </div>
      </div>
      <div class="card preview-card">
        <div class="preview-title">Graph-first 구조</div>
        <div class="mini-grid">
          <div class="mini-card"><div class="mini-label">Step 1</div><div class="mini-value">repo 5개 수집</div></div>
          <div class="mini-card"><div class="mini-label">Step 2</div><div class="mini-value">Upstage 그래프</div></div>
          <div class="mini-card"><div class="mini-label">Step 3</div><div class="mini-value">노드 선택</div></div>
          <div class="mini-card"><div class="mini-label">Step 4</div><div class="mini-value">repo별 AI 분석</div></div>
        </div>
        <div class="flow-box">
          GitHub ID 입력<br />
          → repo metadata 수집<br />
          → Upstage가 repo 관계 판단<br />
          → graph 먼저 표시<br />
          → 노드 클릭 후 AI 분석 시작
        </div>
      </div>
    </section>
  `);

  document.getElementById("github-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = document.getElementById("username").value.trim();
    if (!username) return;
    await scan(username);
  });

  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("username").value = button.dataset.sample;
    });
  });
}

function renderLoading() {
  app.innerHTML = shell(`
    <section class="loading-page">
      <div class="card loading-card">
        <div class="spinner"></div>
        <h2>프로젝트 그래프를 생성하고 있어요</h2>
        <p class="muted">
          GitHub에서 최근 업데이트 기준 상위 5개 repository를 가져오고,
          Upstage/Solar LLM으로 repo 간 관계만 빠르게 판단 중입니다.
        </p>
      </div>
    </section>
  `);
}

function normalizeError(error) {
  if (!error) return { title: "알 수 없는 오류", message: "분석 중 문제가 발생했습니다." };
  if (typeof error === "string") return { title: "분석 실패", message: error };
  if (error.title || error.message) return { title: error.title || "분석 실패", message: error.message || "요청을 처리하지 못했습니다." };
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

async function scan(username) {
  state.username = username;
  state.view = "loading";
  state.error = null;
  state.response = null;
  state.selectedProjectId = null;
  state.analysisByProjectId = {};
  state.analysisErrorByProjectId = {};
  render();

  const controller = new AbortController();
  const timeoutMs = 70000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}/github/scan-user?username=${encodeURIComponent(username)}&limit=${state.limit}`;
    const res = await fetch(url, { method: "POST", signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw body.detail || body || `HTTP ${res.status}`;
    }
    state.response = body;
    state.selectedProjectId = body.projects?.[0]?.project_id || null;
    state.view = "result";
    render();
  } catch (error) {
    if (error?.name === "AbortError") {
      state.error = {
        title: "그래프 생성 시간이 너무 오래 걸립니다",
        message: "GitHub 또는 Upstage 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
      };
    } else {
      state.error = error;
    }
    state.view = "error";
    render();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function analyzeSelectedRepo(project) {
  if (!project?.repo?.full_name) return;
  const projectId = project.project_id;
  state.analyzingProjectId = projectId;
  state.analysisErrorByProjectId[projectId] = null;
  renderResult();

  const controller = new AbortController();
  const timeoutMs = 120000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}/github/analyze-repo?full_name=${encodeURIComponent(project.repo.full_name)}`;
    const res = await fetch(url, { method: "POST", signal: controller.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw body.detail || body || `HTTP ${res.status}`;
    }
    state.analysisByProjectId[projectId] = body.project;
  } catch (error) {
    if (error?.name === "AbortError") {
      state.analysisErrorByProjectId[projectId] = {
        title: "AI 분석 시간이 너무 오래 걸립니다",
        message: "해당 repo 분석이 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
      };
    } else {
      state.analysisErrorByProjectId[projectId] = error;
    }
  } finally {
    state.analyzingProjectId = null;
    clearTimeout(timeoutId);
    renderResult();
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

  for (const edge of state.response?.graph?.edges || []) {
    if (projectIds.has(edge.source) && projectIds.has(edge.target)) {
      const key = [edge.source, edge.target, edge.relation].sort().join("::");
      if (!seen.has(key)) {
        seen.add(key);
        edges.push(edge);
      }
    }
  }

  for (const project of projects) {
    for (const target of project.related_project_ids || []) {
      if (!projectIds.has(target)) continue;
      const key = [project.project_id, target, "related"].sort().join("::");
      if (!seen.has(key)) {
        seen.add(key);
        edges.push({ source: project.project_id, target, relation: "related" });
      }
    }
  }

  return { nodes: projects, edges };
}

function renderProjectGraph() {
  const { nodes, edges } = makeProjectNetwork();
  const width = 760;
  const height = 640;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const positions = new Map();

  nodes.forEach((project, index) => {
    const angle = nodes.length === 1 ? -Math.PI / 2 : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
    positions.set(project.project_id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });

  const edgeSvg = edges.map((edge) => {
    const s = positions.get(edge.source);
    const t = positions.get(edge.target);
    if (!s || !t) return "";
    const active = edge.source === state.selectedProjectId || edge.target === state.selectedProjectId;
    return `<line class="edge ${active ? "active" : ""}" x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" />`;
  }).join("");

  const nodeSvg = nodes.map((project) => {
    const p = positions.get(project.project_id);
    const selected = project.project_id === state.selectedProjectId;
    const analyzed = Boolean(state.analysisByProjectId[project.project_id]);
    const label = truncate(project.repo?.name || project.project_id, 18);
    return `
      <g class="node ${selected ? "selected" : ""} ${analyzed ? "analyzed" : ""}" data-project-id="${escapeHtml(project.project_id)}" transform="translate(${p.x},${p.y})">
        <circle r="48"></circle>
        <text y="5">${escapeHtml(label)}</text>
      </g>
    `;
  }).join("");

  return `
    <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Project knowledge graph">
      ${edgeSvg}
      ${nodeSvg}
    </svg>
    <div class="legend">
      <span>노드: GitHub repository</span>
      <span>선: Upstage가 판단한 repo 관계</span>
      <span>클릭: 기본 정보 및 AI 분석</span>
    </div>
  `;
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

function renderBasicRepo(project) {
  const repo = project.repo || {};
  const graphNode = state.response?.graph?.nodes?.find((node) => node.id === project.project_id);
  const summary = graphNode?.meta?.short_summary || repo.description || "설명이 없는 repository입니다.";
  const shortDomain = graphNode?.meta?.short_domain || [];
  const related = (project.related_project_ids || []).map((id) => projectById(id)?.repo?.name || id);
  const analysisError = state.analysisErrorByProjectId[project.project_id];
  const normalized = analysisError ? normalizeError(analysisError) : null;
  const isAnalyzing = state.analyzingProjectId === project.project_id;

  return `
    <div class="detail-section">
      <h3>Repository Info</h3>
      <div class="info-list">
        <div class="info-row"><div class="info-key">Summary</div><div class="info-value">${escapeHtml(summary)}</div></div>
        <div class="info-row"><div class="info-key">Full name</div><div class="info-value">${escapeHtml(repo.full_name || "Unknown")}</div></div>
        <div class="info-row"><div class="info-key">Language</div><div class="info-value">${escapeHtml(repo.primary_language || "Unknown")}</div></div>
        <div class="info-row"><div class="info-key">Topics</div><div class="tags">${tagList(repo.topics)}</div></div>
        <div class="info-row"><div class="info-key">Domain hint</div><div class="tags">${tagList(shortDomain)}</div></div>
        <div class="info-row"><div class="info-key">Related</div><div class="tags">${tagList(related)}</div></div>
      </div>
    </div>

    <div class="detail-section">
      <h3>Upstage Graph Reasons</h3>
      ${listItems(project.relation_reasons)}
    </div>

    <div class="detail-section">
      <h3>AI Deep Analysis</h3>
      <p class="muted">Project DNA, Asset Card, Develop Report는 아직 생성되지 않았습니다. 필요한 repo만 선택적으로 분석하세요.</p>
      ${normalized ? `<div class="report-card"><b>${escapeHtml(normalized.title)}</b><div class="muted" style="margin-top:8px">${escapeHtml(normalized.message)}</div></div>` : ""}
      <button id="analyze-repo" class="primary-btn" ${isAnalyzing ? "disabled" : ""}>${isAnalyzing ? "AI 분석 중..." : "AI 분석 시작"}</button>
    </div>
  `;
}

function renderAnalyzedProject(project) {
  const repo = project.repo || {};
  const dna = project.dna || {};
  const report = project.report || {};
  const preview = projectById(project.project_id);
  const related = (preview?.related_project_ids || []).map((id) => projectById(id)?.repo?.name || id);

  return `
    <div class="detail-section">
      <h3>Project DNA</h3>
      <div class="info-list">
        <div class="info-row"><div class="info-key">Summary</div><div class="info-value">${escapeHtml(dna.summary || repo.description || "분석 결과가 없습니다.")}</div></div>
        <div class="info-row"><div class="info-key">Target</div><div class="info-value">${escapeHtml(dna.target_user || "Unknown")}</div></div>
        <div class="info-row"><div class="info-key">Problem</div><div class="info-value">${escapeHtml(dna.core_problem || "Unknown")}</div></div>
        <div class="info-row"><div class="info-key">Domain</div><div class="tags">${tagList(dna.domain)}</div></div>
        <div class="info-row"><div class="info-key">Features</div><div class="tags">${tagList(dna.core_features)}</div></div>
        <div class="info-row"><div class="info-key">Tech</div><div class="tags">${tagList(dna.tech_stack?.length ? dna.tech_stack : repo.languages)}</div></div>
      </div>
    </div>

    <div class="detail-section">
      <h3>Selected Core Files</h3>
      ${(project.selected_files || []).length ? (project.selected_files || []).map((file) => `
        <div class="report-card">
          <b>${escapeHtml(file.path)}</b>
          <div class="muted" style="margin-top:8px">${escapeHtml(file.reason || "LLM이 핵심 분석 파일로 선택했습니다.")}</div>
        </div>
      `).join("") : `<div class="empty-state">선택된 핵심 파일이 없습니다.</div>`}
    </div>

    <div class="detail-section">
      <h3>Reusable Asset Cards</h3>
      ${(project.assets || []).map((asset) => `
        <div class="asset-card">
          <div class="asset-top"><div class="asset-name">${escapeHtml(asset.name)}</div><div class="score">reuse ${Math.round((asset.reuse_score || 0) * 100)}%</div></div>
          <div class="muted" style="margin-top:6px">${escapeHtml(asset.type)}</div>
          ${asset.reusable_for?.length ? `<div style="margin-top:10px"><b>활용 가능</b>${listItems(asset.reusable_for)}</div>` : ""}
          ${asset.improvement_needed?.length ? `<div style="margin-top:10px"><b>보완 필요</b>${listItems(asset.improvement_needed)}</div>` : ""}
        </div>
      `).join("") || `<div class="empty-state">Asset Card가 없습니다.</div>`}
    </div>

    <div class="detail-section">
      <h3>Develop Report</h3>
      <div class="report-card"><b>Limitations</b>${listItems(report.limitations)}</div>
      <div class="report-card"><b>Develop Points</b>${listItems(report.develop_points)}</div>
      <div class="report-card"><b>Keep</b>${listItems(report.keep)}</div>
      <div class="report-card"><b>Modify</b>${listItems(report.modify)}</div>
      <div class="report-card"><b>Drop</b>${listItems(report.drop)}</div>
    </div>

    <div class="detail-section">
      <h3>File Tree Suggestion</h3>
      ${listItems(report.file_tree_suggestion)}
    </div>

    <div class="detail-section">
      <h3>Related Projects</h3>
      <div class="tags">${tagList(related)}</div>
    </div>

    <div class="detail-section">
      <h3>Next Build</h3>
      ${listItems(report.next_builds)}
    </div>
  `;
}

function renderProjectDetail(preview) {
  if (!preview) {
    return `<div class="card panel detail-panel"><div class="empty-state">프로젝트 노드를 선택해주세요.</div></div>`;
  }
  const repo = preview.repo || {};
  const analyzed = state.analysisByProjectId[preview.project_id];
  return `
    <aside class="card panel detail-panel">
      <div class="project-header">
        <div>
          <h2 class="project-name">${escapeHtml(repo.name || preview.project_id)}</h2>
          <a class="repo-link" href="${escapeHtml(repo.html_url || "#")}" target="_blank" rel="noreferrer">GitHub에서 보기 →</a>
        </div>
        <div class="badge">${escapeHtml(repo.primary_language || "Repo")}</div>
      </div>
      ${analyzed ? renderAnalyzedProject(analyzed) : renderBasicRepo(preview)}
    </aside>
  `;
}

function renderResult() {
  const projects = state.response?.projects || [];
  const selected = projectById(state.selectedProjectId) || projects[0] || null;
  if (selected && selected.project_id !== state.selectedProjectId) state.selectedProjectId = selected.project_id;

  app.innerHTML = shell(`
    <section class="result-layout">
      <div class="card panel graph-wrap">
        <div class="section-head">
          <div>
            <div class="section-title">${escapeHtml(state.response?.username || state.username)}의 Project Graph</div>
            <div class="muted">${projects.length}개 repository를 Upstage가 관계 그래프로 연결했습니다.</div>
          </div>
          <button id="new-search" class="secondary-btn">다른 ID</button>
        </div>
        ${renderProjectGraph()}
      </div>
      ${renderProjectDetail(selected)}
    </section>
  `);

  document.getElementById("new-search").addEventListener("click", () => {
    state.view = "home";
    state.response = null;
    state.selectedProjectId = null;
    state.analysisByProjectId = {};
    state.analysisErrorByProjectId = {};
    render();
  });

  document.querySelectorAll(".node[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedProjectId = node.dataset.projectId;
      renderResult();
    });
  });

  const analyzeButton = document.getElementById("analyze-repo");
  if (analyzeButton && selected) {
    analyzeButton.addEventListener("click", () => analyzeSelectedRepo(selected));
  }
}

function render() {
  if (state.view === "loading") return renderLoading();
  if (state.view === "error") return renderError();
  if (state.view === "result") return renderResult();
  return renderHome();
}

render();
