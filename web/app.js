const API_BASE_URL =
  localStorage.getItem("GITMESH_API_BASE_URL") || "http://127.0.0.1:8000";

const state = {
  view: "home", // home | loading | result | report | error
  username: "",
  limit: 5,
  response: null,
  selectedProjectId: null,
  previewProjectId: null,
  analyzingProjectId: null,
  analysisByProjectId: {},
  analysisErrorByProjectId: {},
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
          GitMesh는 최근 업데이트 기준 상위 5개 public repository를 먼저 그래프로 보여주고,
          관심 있는 repo만 선택해 Upstage/Solar 기반 AI 분석을 실행합니다.
        </p>

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

        <div class="sample-row">
          <button class="sample-chip" data-sample="octocat">octocat</button>
          <button class="sample-chip" data-sample="torvalds">torvalds</button>
          <button class="sample-chip" data-sample="gaearon">gaearon</button>
        </div>
      </div>

      <div class="card preview-card">
        <div class="preview-title">GitMesh Flow</div>
        <div class="mini-grid">
          <div class="mini-card">
            <div class="mini-label">Step 1</div>
            <div class="mini-value">Repo Graph</div>
          </div>
          <div class="mini-card">
            <div class="mini-label">Step 2</div>
            <div class="mini-value">Repo Preview</div>
          </div>
          <div class="mini-card">
            <div class="mini-label">Step 3</div>
            <div class="mini-value">AI Analysis</div>
          </div>
          <div class="mini-card">
            <div class="mini-label">Step 4</div>
            <div class="mini-value">Report Page</div>
          </div>
        </div>

        <div class="flow-box">
          GitHub ID 입력<br />
          → 상위 5개 public repo 수집<br />
          → Upstage가 repo 관계 graph 생성<br />
          → 노드 클릭 시 repo preview<br />
          → AI 분석 후 별도 report page에서 확인
        </div>
      </div>
    </section>
  `);

  document.getElementById("github-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = document.getElementById("username").value.trim();
    if (!username) return;
    await scanUser(username);
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
        <h2>GitHub 프로젝트 그래프를 만들고 있어요</h2>
        <p class="muted">
          최근 업데이트 기준 상위 5개 repository의 metadata를 수집하고,
          Upstage/Solar가 repo 간 관계를 판단하는 중입니다.
        </p>
      </div>
    </section>
  `);
}

function normalizeError(error) {
  if (!error) {
    return {
      title: "알 수 없는 오류",
      message: "분석 중 문제가 발생했습니다.",
    };
  }

  if (typeof error === "string") {
    return {
      title: "분석 실패",
      message: error,
    };
  }

  if (error.title || error.message) {
    return {
      title: error.title || "분석 실패",
      message: error.message || "요청을 처리하지 못했습니다.",
    };
  }

  return {
    title: "분석 실패",
    message: JSON.stringify(error),
  };
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
  state.username = username;
  state.view = "loading";
  state.error = null;
  state.response = null;
  state.selectedProjectId = null;
  state.previewProjectId = null;
  state.analysisByProjectId = {};
  state.analysisErrorByProjectId = {};
  render();

  const controller = new AbortController();
  const timeoutMs = 120000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}/github/scan-user?username=${encodeURIComponent(
      username
    )}&limit=${state.limit}`;

    const res = await fetch(url, {
      method: "POST",
      signal: controller.signal,
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw body.detail || body || `HTTP ${res.status}`;
    }

    state.response = body;
    state.selectedProjectId = body.projects?.[0]?.project_id || null;
    state.previewProjectId = null;
    state.view = "result";
    render();
  } catch (error) {
    if (error?.name === "AbortError") {
      state.error = {
        title: "그래프 생성 시간이 너무 오래 걸립니다",
        message:
          "GitHub 또는 Upstage 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
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
        edges.push({
          source: project.project_id,
          target,
          relation: "related",
        });
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

  return {
    nodes: projects,
    edges,
  };
}

function renderProjectGraph() {
  const { nodes, edges } = makeProjectNetwork();

  const width = 880;
  const height = 620;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const positions = new Map();

  nodes.forEach((project, index) => {
    const angle =
      nodes.length === 1
        ? -Math.PI / 2
        : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;

    positions.set(project.project_id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });

  const edgeSvg = edges
    .map((edge) => {
      const s = positions.get(edge.source);
      const t = positions.get(edge.target);
      if (!s || !t) return "";

      const active =
        edge.source === state.selectedProjectId ||
        edge.target === state.selectedProjectId ||
        edge.source === state.previewProjectId ||
        edge.target === state.previewProjectId;

      return `
        <line
          class="edge ${active ? "active" : ""}"
          x1="${s.x}"
          y1="${s.y}"
          x2="${t.x}"
          y2="${t.y}"
        />
      `;
    })
    .join("");

  const nodeSvg = nodes
    .map((project) => {
      const p = positions.get(project.project_id);
      const selected =
        project.project_id === state.selectedProjectId ||
        project.project_id === state.previewProjectId;

      const label = truncate(project.repo?.name || project.project_id, 18);
      const language = project.repo?.primary_language || "";

      return `
        <g
          class="node ${selected ? "selected" : ""}"
          data-project-id="${escapeHtml(project.project_id)}"
          transform="translate(${p.x},${p.y})"
        >
          <circle r="52"></circle>
          <text y="-4" class="node-label">${escapeHtml(label)}</text>
          <text y="16" class="node-sub">${escapeHtml(language)}</text>
        </g>
      `;
    })
    .join("");

  return `
    <div class="graph-canvas">
      <svg
        class="graph-svg"
        viewBox="0 0 ${width} ${height}"
        role="img"
        aria-label="Project knowledge graph"
      >
        ${edgeSvg}
        ${nodeSvg}
      </svg>
    </div>

    <div class="legend">
      <span>노드: GitHub repository</span>
      <span>선: 유사성·재사용·협업 가능성</span>
      <span>노드 클릭: repo preview</span>
    </div>
  `;
}

function listItems(items) {
  const values = (items || []).filter(Boolean);

  if (!values.length) {
    return `<div class="empty-state">아직 분석된 항목이 없습니다.</div>`;
  }

  return `
    <ul class="ul">
      ${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
}

function tagList(items) {
  const values = (items || []).filter(Boolean);

  if (!values.length) {
    return `<span class="tag">None</span>`;
  }

  return values.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("");
}

function getRelatedProjectNames(project) {
  return (project.related_project_ids || [])
    .map((id) => projectById(id)?.repo?.name || id)
    .filter(Boolean);
}

function renderRepoPreviewModal(project) {
  if (!project) return "";

  const repo = project.repo || {};
  const analyzed = state.analysisByProjectId[project.project_id];
  const isAnalyzing = state.analyzingProjectId === project.project_id;
  const analysisError = state.analysisErrorByProjectId[project.project_id];
  const related = getRelatedProjectNames(project);

  return `
    <div class="modal-backdrop" id="modal-backdrop">
      <section class="repo-modal card">
        <button class="modal-close" id="modal-close" aria-label="close">×</button>

        <div class="modal-kicker">Repository Preview</div>
        <h2 class="modal-title">${escapeHtml(repo.name || project.project_id)}</h2>

        <p class="modal-desc">
          ${escapeHtml(repo.description || "No repository description.")}
        </p>

        <div class="repo-meta-grid">
          <div class="repo-meta-item">
            <div class="repo-meta-label">Full Name</div>
            <div class="repo-meta-value">${escapeHtml(repo.full_name || "-")}</div>
          </div>
          <div class="repo-meta-item">
            <div class="repo-meta-label">Language</div>
            <div class="repo-meta-value">${escapeHtml(repo.primary_language || "-")}</div>
          </div>
          <div class="repo-meta-item">
            <div class="repo-meta-label">Stars</div>
            <div class="repo-meta-value">${escapeHtml(repo.stars ?? 0)}</div>
          </div>
          <div class="repo-meta-item">
            <div class="repo-meta-label">Forks</div>
            <div class="repo-meta-value">${escapeHtml(repo.forks ?? 0)}</div>
          </div>
        </div>

        <div class="modal-section">
          <div class="modal-section-title">Topics</div>
          <div class="tags">${tagList(repo.topics)}</div>
        </div>

        <div class="modal-section">
          <div class="modal-section-title">Related Repositories</div>
          <div class="tags">${tagList(related)}</div>
        </div>

        ${
          analysisError
            ? `
              <div class="inline-error">
                <b>${escapeHtml(normalizeError(analysisError).title)}</b>
                <p>${escapeHtml(normalizeError(analysisError).message)}</p>
              </div>
            `
            : ""
        }

        <div class="modal-actions">
          <a
            class="secondary-btn link-btn"
            href="${escapeHtml(repo.html_url || "#")}"
            target="_blank"
            rel="noreferrer"
          >
            GitHub 열기
          </a>

          ${
            analyzed
              ? `
                <button id="open-report" class="primary-btn">
                  분석 리포트 보기
                </button>
              `
              : `
                <button id="analyze-repo" class="primary-btn" ${isAnalyzing ? "disabled" : ""}>
                  ${isAnalyzing ? "AI 분석 중..." : "AI 분석 시작"}
                </button>
              `
          }
        </div>
      </section>
    </div>
  `;
}

function renderResult() {
  const projects = state.response?.projects || [];
  const selected = projectById(state.selectedProjectId) || projects[0] || null;
  const previewProject = projectById(state.previewProjectId);

  if (selected && selected.project_id !== state.selectedProjectId) {
    state.selectedProjectId = selected.project_id;
  }

  app.innerHTML = shell(`
    <section class="graph-page">
      <div class="graph-header">
        <div>
          <div class="section-title">
            ${escapeHtml(state.response?.username || state.username)}의 GitMesh Graph
          </div>
          <div class="muted">
            최근 업데이트 기준 ${projects.length}개 public repository를 그래프로 연결했습니다.
          </div>
        </div>

        <button id="new-search" class="secondary-btn">다른 GitHub ID</button>
      </div>

      <div class="card graph-panel">
        ${renderProjectGraph()}
      </div>

      ${renderRepoPreviewModal(previewProject)}
    </section>
  `);

  document.getElementById("new-search").addEventListener("click", () => {
    state.view = "home";
    state.response = null;
    state.selectedProjectId = null;
    state.previewProjectId = null;
    render();
  });

  document.querySelectorAll(".node[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const projectId = node.dataset.projectId;
      state.selectedProjectId = projectId;
      state.previewProjectId = projectId;
      renderResult();
    });
  });

  const closeButton = document.getElementById("modal-close");
  if (closeButton) {
    closeButton.addEventListener("click", () => {
      state.previewProjectId = null;
      renderResult();
    });
  }

  const backdrop = document.getElementById("modal-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", (event) => {
      if (event.target.id === "modal-backdrop") {
        state.previewProjectId = null;
        renderResult();
      }
    });
  }

  const analyzeButton = document.getElementById("analyze-repo");
  if (analyzeButton && previewProject) {
    analyzeButton.addEventListener("click", () => {
      analyzeSelectedRepo(previewProject, { goToReport: true });
    });
  }

  const reportButton = document.getElementById("open-report");
  if (reportButton && previewProject) {
    reportButton.addEventListener("click", () => {
      state.selectedProjectId = previewProject.project_id;
      state.view = "report";
      state.previewProjectId = null;
      render();
    });
  }
}

async function analyzeSelectedRepo(project, options = {}) {
  if (!project?.repo?.full_name) return;

  const projectId = project.project_id;
  state.analyzingProjectId = projectId;
  state.analysisErrorByProjectId[projectId] = null;
  renderResult();

  const controller = new AbortController();
  const timeoutMs = 120000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}/github/analyze-repo?full_name=${encodeURIComponent(
      project.repo.full_name
    )}`;

    const res = await fetch(url, {
      method: "POST",
      signal: controller.signal,
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw body.detail || body || `HTTP ${res.status}`;
    }

    state.analysisByProjectId[projectId] = body.project;

    if (options.goToReport) {
      state.selectedProjectId = projectId;
      state.previewProjectId = null;
      state.view = "report";
      render();
    } else {
      renderResult();
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      state.analysisErrorByProjectId[projectId] = {
        title: "AI 분석 시간이 너무 오래 걸립니다",
        message: "해당 repo 분석이 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
      };
    } else {
      state.analysisErrorByProjectId[projectId] = error;
    }

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

  if (!preview) {
    state.view = "result";
    render();
    return;
  }

  if (!analyzed) {
    app.innerHTML = shell(`
      <section class="report-page">
        <div class="report-topbar">
          <button id="back-to-graph" class="secondary-btn">← 그래프로 돌아가기</button>
        </div>

        <div class="card report-empty">
          <h2>아직 분석 결과가 없습니다</h2>
          <p class="muted">
            ${escapeHtml(preview.repo?.name || "선택한 repo")}의 AI 분석을 먼저 실행해주세요.
          </p>
          <button id="start-analysis" class="primary-btn">AI 분석 시작</button>
        </div>
      </section>
    `);

    document.getElementById("back-to-graph").addEventListener("click", () => {
      state.view = "result";
      render();
    });

    document.getElementById("start-analysis").addEventListener("click", () => {
      analyzeSelectedRepo(preview, { goToReport: true });
    });

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
        <a
          class="secondary-btn link-btn"
          href="${escapeHtml(repo.html_url || "#")}"
          target="_blank"
          rel="noreferrer"
        >
          GitHub 열기
        </a>
      </div>

      <header class="report-hero card">
        <div class="report-kicker">AI Project Report</div>
        <h1>${escapeHtml(repo.name || preview.project_id)}</h1>
        <p>${escapeHtml(dna.summary || repo.description || "Repository analysis report.")}</p>

        <div class="report-tags">
          ${tagList(dna.domain)}
          ${tagList(dna.tech_stack?.length ? dna.tech_stack : repo.languages)}
        </div>
      </header>

      <section class="report-grid">
        <div class="card report-card-large">
          <h2>Project DNA</h2>
          <div class="info-list">
            <div class="info-row">
              <div class="info-key">Target User</div>
              <div class="info-value">${escapeHtml(dna.target_user || "Unknown")}</div>
            </div>
            <div class="info-row">
              <div class="info-key">Core Problem</div>
              <div class="info-value">${escapeHtml(dna.core_problem || "Unknown")}</div>
            </div>
            <div class="info-row">
              <div class="info-key">Core Features</div>
              <div class="info-value tags">${tagList(dna.core_features)}</div>
            </div>
            <div class="info-row">
              <div class="info-key">Tech Stack</div>
              <div class="info-value tags">
                ${tagList(dna.tech_stack?.length ? dna.tech_stack : repo.languages)}
              </div>
            </div>
          </div>
        </div>

        <div class="card report-card-large">
          <h2>Develop Report</h2>

          <div class="report-subcard">
            <b>Limitations</b>
            ${listItems(report.limitations)}
          </div>

          <div class="report-subcard">
            <b>Develop Points</b>
            ${listItems(report.develop_points)}
          </div>

          <div class="report-subcard">
            <b>Keep</b>
            ${listItems(report.keep)}
          </div>

          <div class="report-subcard">
            <b>Modify</b>
            ${listItems(report.modify)}
          </div>

          <div class="report-subcard">
            <b>Drop</b>
            ${listItems(report.drop)}
          </div>
        </div>
      </section>

      <section class="report-section">
        <h2>Reusable Asset Cards</h2>
        <div class="asset-grid">
          ${
            (analyzed.assets || [])
              .map(
                (asset) => `
                  <div class="card asset-card">
                    <div class="asset-top">
                      <div>
                        <div class="asset-name">${escapeHtml(asset.name)}</div>
                        <div class="asset-type">${escapeHtml(asset.type)}</div>
                      </div>
                      <div class="score">reuse ${Math.round((asset.reuse_score || 0) * 100)}%</div>
                    </div>

                    <div class="asset-block">
                      <b>활용 가능</b>
                      ${listItems(asset.reusable_for)}
                    </div>

                    <div class="asset-block">
                      <b>보완 필요</b>
                      ${listItems(asset.improvement_needed)}
                    </div>
                  </div>
                `
              )
              .join("") || `<div class="empty-state">Asset Card가 없습니다.</div>`
          }
        </div>
      </section>

      <section class="report-grid">
        <div class="card report-card-large">
          <h2>Selected Core Files</h2>
          ${
            selectedFiles.length
              ? selectedFiles
                  .map(
                    (file) => `
                      <div class="file-card">
                        <div class="file-path">${escapeHtml(file.path)}</div>
                        <div class="file-reason">${escapeHtml(file.reason || "Selected for analysis.")}</div>
                      </div>
                    `
                  )
                  .join("")
              : `<div class="empty-state">선택된 핵심 파일 정보가 없습니다.</div>`
          }
        </div>

        <div class="card report-card-large">
          <h2>File Tree Suggestion</h2>
          ${listItems(report.file_tree_suggestion)}

          <h2 style="margin-top: 28px;">Next Build</h2>
          ${listItems(report.next_builds)}
        </div>
      </section>
    </section>
  `);

  document.getElementById("back-to-graph").addEventListener("click", () => {
    state.view = "result";
    render();
  });
}

function render() {
  if (state.view === "loading") return renderLoading();
  if (state.view === "error") return renderError();
  if (state.view === "result") return renderResult();
  if (state.view === "report") return renderReportPage();
  return renderHome();
}

render();