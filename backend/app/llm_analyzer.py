from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import Any

from openai import OpenAI

from .models import (
    AssetCard,
    DevelopReport,
    FileScanResponse,
    GraphEdge,
    GraphNode,
    ProjectDNA,
    ProjectGraph,
    ProjectPreview,
    ProjectReport,
    RepoSummary,
    ScanResponse,
    SelectedFile,
    UploadedFileSummary,
)


class LLMAnalysisError(RuntimeError):
    """Raised when Upstage/Solar analysis cannot be completed."""


SINGLE_REPO_SYSTEM_PROMPT = """
You are GitMesh, an expert AI product strategist and software architect.
Analyze one GitHub repository deeply. The user-facing analysis must be organized into exactly three pillars:
1) Asset Card, 2) Develop Point, 3) Roadmap.
Project DNA may still be returned as compact metadata, but the main value must come from assets, develop_points, and roadmap-style next_builds.
Return ONLY a valid JSON object. Do not include markdown, code fences, comments, or prose outside JSON.
Use Korean for natural-language values.
""".strip()

GRAPH_SYSTEM_PROMPT = """
You are GitMesh Graph Agent.
Your job is to quickly infer useful relationships among a user's GitHub repositories.
You do NOT create full project reports. You only create a lightweight repository relationship graph.
Return ONLY a valid JSON object. Do not include markdown, code fences, comments, or prose outside JSON.
Use Korean for reason, label, and summary values.
""".strip()

FILE_SELECT_SYSTEM_PROMPT = """
You are GitMesh File Selector.
Given a GitHub repository metadata, README excerpt, and file tree, select the most important files
that should be read to understand the repository architecture, core logic, UI entrypoints, API flow,
agent workflow, data processing, and configuration.
Return ONLY a valid JSON object. Do not include markdown, code fences, comments, or prose outside JSON.
Use Korean for reason values.
""".strip()

FILE_GRAPH_SYSTEM_PROMPT = """
You are GitMesh File Graph Agent.
The user uploaded multiple project-related files. Infer relationships among the files and create a lightweight file graph.
Return ONLY a valid JSON object. Do not include markdown, code fences, comments, or prose outside JSON.
Use Korean for reason, label, and summary values.
""".strip()

SINGLE_FILE_SYSTEM_PROMPT = """
You are GitMesh File Project Analyzer.
Analyze one uploaded file as a project artifact. The user-facing analysis must be organized into exactly three pillars:
1) Asset Card, 2) Develop Point, 3) Roadmap.
Project DNA may still be returned as compact metadata, but the main value must come from assets, develop_points, and roadmap-style next_builds.
Return ONLY a valid JSON object. Do not include markdown, code fences, comments, or prose outside JSON.
Use Korean for natural-language values.
""".strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            raise LLMAnalysisError("Upstage 응답에서 JSON 객체를 찾지 못했습니다.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMAnalysisError(
                f"Upstage 응답 JSON 파싱에 실패했습니다: {exc}. 응답 일부: {match.group(0)[:700]}"
            ) from exc


def _upstage_client() -> tuple[OpenAI, str]:
    api_key = os.getenv("UPSTAGE_API_KEY", "").strip()
    if not api_key:
        raise LLMAnalysisError(
            "UPSTAGE_API_KEY가 설정되어 있지 않습니다. backend/.env에 API 키를 넣어주세요."
        )

    model = os.getenv("UPSTAGE_MODEL", "solar-mini").strip() or "solar-mini"
    base_url = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1").strip()
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=0)
    return client, model


def _chat_json_completion(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    error_context: str,
) -> dict[str, Any]:
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise LLMAnalysisError(f"{error_context} 호출에 실패했습니다: {exc}") from exc

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise LLMAnalysisError(f"{error_context}가 빈 응답을 반환했습니다.")

    return _extract_json_object(content)


def _call_json(system_prompt: str, user_prompt: str, *, temperature: float, error_context: str) -> dict[str, Any]:
    client, model = _upstage_client()
    return _chat_json_completion(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        error_context=error_context,
    )


def _as_str_list(value: Any, *, max_items: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            result.append(text)
    return result[:max_items]


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        score = 0.5
    if score > 1:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _project_id(repo: RepoSummary) -> str:
    return f"repo_{repo.id}"


def _file_project_id(file: UploadedFileSummary) -> str:
    return f"file_{file.id}"


def _repo_payload(
    repo: RepoSummary,
    *,
    include_readme: bool = True,
    include_file_tree: bool = True,
    file_tree_limit: int = 80,
) -> dict[str, Any]:
    payload = {
        "repo_id": repo.id,
        "project_id": _project_id(repo),
        "name": repo.name,
        "full_name": repo.full_name,
        "html_url": repo.html_url,
        "description": repo.description,
        "primary_language": repo.primary_language,
        "languages": repo.languages[:10],
        "topics": repo.topics[:15],
        "stars": repo.stars,
        "forks": repo.forks,
        "default_branch": repo.default_branch,
        "updated_at": repo.updated_at,
    }
    if include_file_tree:
        payload["file_tree_excerpt"] = repo.file_tree[:file_tree_limit]
    if include_readme:
        payload["readme_excerpt"] = (repo.readme_text or "")[:2500]
    return payload


def _file_payload(file: UploadedFileSummary) -> dict[str, Any]:
    return {
        "file_id": file.id,
        "repo_id": file.id,
        "project_id": _file_project_id(file),
        "name": file.name,
        "size": file.size,
        "mime_type": file.mime_type,
        "content_excerpt": file.content_excerpt[:4500],
    }


def _build_graph_prompt(username: str, repos: list[RepoSummary]) -> str:
    schema = {
        "project_summaries": [
            {"project_id": "repo_<repo_id from input>", "short_summary": "repo의 용도 1문장", "short_domain": ["도메인 키워드 최대 3개"]}
        ],
        "edges": [
            {
                "source_project_id": "repo_<repo_id from input>",
                "target_project_id": "repo_<repo_id from input>",
                "relation": "similar_to | shares_domain_with | shares_tech_with | can_collaborate_with | can_reuse_asset_from | can_improve_with",
                "weight": 0.0,
                "reason": "두 repo를 연결한 구체적 이유",
            }
        ],
        "next_builds": [
            {"id": "next_1", "label": "두 개 이상의 repo를 결합해 만들 수 있는 다음 프로젝트명", "project_ids": ["repo_<repo_id>", "repo_<repo_id>"], "reason": "왜 이 next build가 가능한지"}
        ],
    }
    payload = {
        "task": "Create a lightweight GitMesh repository relationship graph. Do not perform deep repo analysis.",
        "rules": [
            "Use only repository metadata in the input. Do not assume file contents.",
            "All source_project_id and target_project_id must exactly match input project_id values.",
            "Prefer meaningful relationships over many weak edges. Create at most 14 edges.",
            "If repositories are unrelated, create fewer edges rather than forcing relationships.",
            "Create at most 3 next_builds. A next_build must combine at least 2 repositories.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "github_username": username,
        "repositories": [_repo_payload(repo, include_readme=False, include_file_tree=False) for repo in repos],
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_file_graph_prompt(files: list[UploadedFileSummary]) -> str:
    schema = {
        "file_summaries": [
            {"project_id": "file_<file_id from input>", "short_summary": "파일의 역할 1문장", "short_domain": ["문서/코드/기획 등 키워드 최대 3개"]}
        ],
        "edges": [
            {
                "source_project_id": "file_<file_id from input>",
                "target_project_id": "file_<file_id from input>",
                "relation": "similar_to | same_project | depends_on | complements | can_be_combined_with | improves",
                "weight": 0.0,
                "reason": "두 파일을 연결한 구체적 이유",
            }
        ],
        "next_builds": [
            {"id": "next_1", "label": "여러 파일을 결합해 만들 수 있는 프로젝트/산출물명", "project_ids": ["file_<file_id>", "file_<file_id>"], "reason": "왜 이 next build가 가능한지"}
        ],
    }
    payload = {
        "task": "Create a lightweight file relationship graph from uploaded project artifacts.",
        "rules": [
            "Use uploaded file names, mime types, and text excerpts only.",
            "All source_project_id and target_project_id must exactly match input project_id values.",
            "Create at most 14 edges.",
            "Create at most 5 next_builds.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "files": [_file_payload(file) for file in files],
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_file_selection_prompt(repo: RepoSummary, candidate_paths: list[str]) -> str:
    schema = {"selected_files": [{"path": "path exactly from candidate_paths", "reason": "왜 이 파일이 프로젝트 분석에 중요한지"}]}
    instruction = {
        "task": "Select up to 4 important files to read before deep GitMesh repo analysis.",
        "rules": [
            "Choose files only from candidate_paths. Paths must match exactly.",
            "Prefer entrypoints, API routes, agent/workflow logic, service modules, UI entrypoints, configuration and dependency files.",
            "Do not select generated files, lock files, images, fonts, binary assets, dependency folders, build outputs, or test snapshots.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "repository": _repo_payload(repo, include_readme=True, include_file_tree=False),
        "candidate_paths": candidate_paths[:240],
    }
    return json.dumps(instruction, ensure_ascii=False)


def _important_files_payload(important_files: list[SelectedFile]) -> list[dict[str, str]]:
    return [
        {"path": file.path, "selection_reason": file.reason, "content_excerpt": file.content_excerpt[:2500]}
        for file in important_files[:4]
    ]


def _build_single_repo_prompt(repo: RepoSummary, important_files: list[SelectedFile] | None = None) -> str:
    schema = {
        "repo_id": "GitHub repo id from input",
        "project_id": "repo_<repo_id>",
        "dna": {"domain": ["최대 3개"], "target_user": "주요 사용자", "core_problem": "이 프로젝트가 해결하려는 핵심 문제", "core_features": ["핵심 기능 3~6개"], "tech_stack": ["기술 스택 3~8개"], "summary": "프로젝트 요약 1~2문장"},
        "assets": [{"name": "재사용 가능한 자산명", "type": "Code | UI | Prompt | Data | Architecture | Domain Knowledge | Documentation", "reuse_score": 0.0, "reusable_for": ["재사용 가능한 프로젝트/도메인"], "improvement_needed": ["재사용 전 보완점"]}],
        "report": {"limitations": ["내부 진단용 한계점"], "develop_points": ["구체적인 개선/고도화 포인트 8~10개"], "keep": ["내부 진단용 유지할 것"], "modify": ["내부 진단용 수정할 것"], "drop": ["내부 진단용 후순위"], "next_builds": ["Roadmap 단계 5~7개: 무엇을 어떤 순서로 구현할지"], "file_tree_suggestion": ["내부 진단용 구조 제안"]},
    }
    instruction = {
        "task": "Analyze this GitHub repository and produce GitMesh single-repo JSON.",
        "rules": [
            "Use only repository information in the input.",
            "repo_id and project_id must match input values.",
            "Create 3-5 high-quality asset cards. Each asset must be reusable and specific to this repo.",
            "Prioritize report.develop_points. Generate 8-10 concrete develop_points. Each point must explain what to improve, why it matters, and how to implement it.",
            "Use report.next_builds as the Roadmap section. Generate 5-7 ordered roadmap steps, not vague next-project ideas.",
            "Roadmap items should be practical execution steps such as refactor, API separation, UI improvement, validation, deployment, user testing, or metric tracking.",
            "Avoid generic advice such as 'improve documentation' unless you specify exactly what should be documented and where.",
            "Do not focus on explaining which files were read. Use selected files only as hidden evidence for the analysis.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "repository": _repo_payload(repo, include_readme=True, include_file_tree=True, file_tree_limit=80),
        "important_files_read_by_github_contents_api": _important_files_payload(important_files or []),
    }
    return json.dumps(instruction, ensure_ascii=False)


def _build_single_file_prompt(file: UploadedFileSummary) -> str:
    schema = {
        "repo_id": "uploaded file id from input",
        "project_id": "file_<file_id>",
        "dna": {"domain": ["최대 3개"], "target_user": "주요 사용자", "core_problem": "이 파일/문서가 다루는 핵심 문제", "core_features": ["핵심 내용/기능/구성 3~6개"], "tech_stack": ["파일에서 확인되는 기술/도구/방법론"], "summary": "파일 요약 1~2문장"},
        "assets": [{"name": "재사용 가능한 자산명", "type": "Code | UI | Prompt | Data | Architecture | Domain Knowledge | Documentation | Planning", "reuse_score": 0.0, "reusable_for": ["재사용 가능한 프로젝트/도메인"], "improvement_needed": ["재사용 전 보완점"]}],
        "report": {"limitations": ["내부 진단용 한계점"], "develop_points": ["구체적인 개선/고도화 포인트 8~10개"], "keep": ["내부 진단용 유지할 것"], "modify": ["내부 진단용 수정할 것"], "drop": ["내부 진단용 후순위"], "next_builds": ["Roadmap 단계 5~7개: 무엇을 어떤 순서로 구현할지"], "file_tree_suggestion": ["내부 진단용 구조 제안"]},
    }
    instruction = {
        "task": "Analyze this uploaded project artifact as a GitMesh file project.",
        "rules": [
            "Use only uploaded file content in the input.",
            "repo_id and project_id must match input values.",
            "Create 3-5 high-quality asset cards grounded in the uploaded file.",
            "Prioritize report.develop_points. Generate 8-10 concrete develop_points. Each point must explain what to improve, why it matters, and how to implement it.",
            "Use report.next_builds as the Roadmap section. Generate 5-7 ordered roadmap steps, not vague next-project ideas.",
            "Make develop_points and roadmap concrete and grounded in the file content. Avoid generic advice.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "file": _file_payload(file),
    }
    return json.dumps(instruction, ensure_ascii=False)


def analyze_project_graph_with_upstage(username: str, repos: list[RepoSummary]) -> ScanResponse:
    data = _call_json(GRAPH_SYSTEM_PROMPT, _build_graph_prompt(username, repos), temperature=0.1, error_context="Upstage Graph API")
    valid_ids = {_project_id(repo) for repo in repos}

    summary_by_id: dict[str, dict[str, Any]] = {}
    for item in data.get("project_summaries") or []:
        if isinstance(item, dict) and item.get("project_id") in valid_ids:
            summary_by_id[str(item["project_id"])] = item

    nodes = [
        GraphNode(
            id=_project_id(repo),
            label=repo.name,
            type="Project",
            meta={
                "repo_url": repo.html_url,
                "language": repo.primary_language,
                "topics": repo.topics,
                "updated_at": repo.updated_at,
                "short_summary": str(summary_by_id.get(_project_id(repo), {}).get("short_summary") or repo.description or ""),
                "short_domain": _as_str_list(summary_by_id.get(_project_id(repo), {}).get("short_domain"), max_items=3),
            },
        )
        for repo in repos
    ]

    related: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, list[str]] = defaultdict(list)
    edges: list[GraphEdge] = []
    allowed_relations = {"similar_to", "shares_domain_with", "shares_tech_with", "can_collaborate_with", "can_reuse_asset_from", "can_improve_with"}

    for raw_edge in data.get("edges") or []:
        if not isinstance(raw_edge, dict):
            continue
        source = str(raw_edge.get("source_project_id") or "").strip()
        target = str(raw_edge.get("target_project_id") or "").strip()
        if source not in valid_ids or target not in valid_ids or source == target:
            continue
        relation = str(raw_edge.get("relation") or "similar_to").strip()
        if relation not in allowed_relations:
            relation = "similar_to"
        reason = str(raw_edge.get("reason") or relation).strip()
        weight = _clamp_score(raw_edge.get("weight", 0.6))
        edges.append(GraphEdge(source=source, target=target, relation=relation, weight=weight, meta={"reason": reason}))
        related[source].add(target)
        related[target].add(source)
        reasons[source].append(reason)
        reasons[target].append(reason)

    for index, raw_next in enumerate(data.get("next_builds") or [], start=1):
        if not isinstance(raw_next, dict):
            continue
        project_ids = [pid for pid in _as_str_list(raw_next.get("project_ids"), max_items=5) if pid in valid_ids]
        if len(project_ids) < 2:
            continue
        next_id = str(raw_next.get("id") or f"next_{index}").strip()
        if not next_id.startswith("next_"):
            next_id = f"next_{index}"
        label = str(raw_next.get("label") or f"Next Build {index}").strip()
        reason = str(raw_next.get("reason") or "여러 repo를 결합할 수 있습니다.").strip()
        nodes.append(GraphNode(id=next_id, label=label, type="NextBuild", meta={"reason": reason, "project_ids": project_ids}))
        for pid in project_ids:
            edges.append(GraphEdge(source=pid, target=next_id, relation="can_create", weight=0.85, meta={"reason": reason}))

    previews = [
        ProjectPreview(
            project_id=_project_id(repo),
            repo=repo,
            related_project_ids=sorted(related.get(_project_id(repo), set()))[:6],
            relation_reasons=reasons.get(_project_id(repo), [])[:6],
            analysis_status="not_started",
        )
        for repo in repos
    ]
    return ScanResponse(username=username, projects=previews, graph=ProjectGraph(nodes=nodes, edges=edges))


def analyze_file_graph_with_upstage(scan_id: str, files: list[UploadedFileSummary]) -> FileScanResponse:
    data = _call_json(FILE_GRAPH_SYSTEM_PROMPT, _build_file_graph_prompt(files), temperature=0.1, error_context="Upstage File Graph API")
    valid_ids = {_file_project_id(file) for file in files}

    summary_by_id: dict[str, dict[str, Any]] = {}
    for item in data.get("file_summaries") or []:
        if isinstance(item, dict) and item.get("project_id") in valid_ids:
            summary_by_id[str(item["project_id"])] = item

    nodes: list[GraphNode] = []
    previews: list[ProjectPreview] = []
    related: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, list[str]] = defaultdict(list)
    edges: list[GraphEdge] = []

    for file in files:
        project_id = _file_project_id(file)
        summary = summary_by_id.get(project_id, {})
        synthetic_repo = RepoSummary(
            id=file.id,
            name=file.name,
            full_name=file.name,
            html_url="#",
            description=str(summary.get("short_summary") or file.mime_type or "Uploaded file"),
            primary_language="File",
            languages=["Uploaded File"],
            topics=_as_str_list(summary.get("short_domain"), max_items=3),
            readme_text=file.content_excerpt[:2500],
            file_tree=[file.name],
        )
        nodes.append(GraphNode(id=project_id, label=file.name, type="File", meta={"mime_type": file.mime_type, "size": file.size, "short_summary": synthetic_repo.description or "", "short_domain": synthetic_repo.topics}))
        previews.append(ProjectPreview(project_id=project_id, repo=synthetic_repo, analysis_status="not_started"))

    allowed_relations = {"similar_to", "same_project", "depends_on", "complements", "can_be_combined_with", "improves"}
    for raw_edge in data.get("edges") or []:
        if not isinstance(raw_edge, dict):
            continue
        source = str(raw_edge.get("source_project_id") or "").strip()
        target = str(raw_edge.get("target_project_id") or "").strip()
        if source not in valid_ids or target not in valid_ids or source == target:
            continue
        relation = str(raw_edge.get("relation") or "similar_to").strip()
        if relation not in allowed_relations:
            relation = "similar_to"
        reason = str(raw_edge.get("reason") or relation).strip()
        weight = _clamp_score(raw_edge.get("weight", 0.6))
        edges.append(GraphEdge(source=source, target=target, relation=relation, weight=weight, meta={"reason": reason}))
        related[source].add(target)
        related[target].add(source)
        reasons[source].append(reason)
        reasons[target].append(reason)

    for preview in previews:
        preview.related_project_ids = sorted(related.get(preview.project_id, set()))[:6]
        preview.relation_reasons = reasons.get(preview.project_id, [])[:6]

    for index, raw_next in enumerate(data.get("next_builds") or [], start=1):
        if not isinstance(raw_next, dict):
            continue
        project_ids = [pid for pid in _as_str_list(raw_next.get("project_ids"), max_items=5) if pid in valid_ids]
        if len(project_ids) < 2:
            continue
        next_id = str(raw_next.get("id") or f"next_{index}").strip()
        if not next_id.startswith("next_"):
            next_id = f"next_{index}"
        label = str(raw_next.get("label") or f"Next Build {index}").strip()
        reason = str(raw_next.get("reason") or "여러 파일을 결합할 수 있습니다.").strip()
        nodes.append(GraphNode(id=next_id, label=label, type="NextBuild", meta={"reason": reason, "project_ids": project_ids}))
        for pid in project_ids:
            edges.append(GraphEdge(source=pid, target=next_id, relation="can_create", weight=0.85, meta={"reason": reason}))

    return FileScanResponse(scan_id=scan_id, username="uploaded-files", projects=previews, graph=ProjectGraph(nodes=nodes, edges=edges))


def select_important_files_with_upstage(repo: RepoSummary, candidate_paths: list[str]) -> list[dict[str, str]]:
    if not candidate_paths:
        raise LLMAnalysisError("분석할 수 있는 텍스트 파일 경로가 없습니다.")
    data = _call_json(FILE_SELECT_SYSTEM_PROMPT, _build_file_selection_prompt(repo, candidate_paths), temperature=0.1, error_context="Upstage 파일 선택 API")
    selected_raw = data.get("selected_files")
    if not isinstance(selected_raw, list):
        raise LLMAnalysisError("Upstage 파일 선택 응답에 selected_files 배열이 없습니다.")

    allowed = set(candidate_paths)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in selected_raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not path or path not in allowed or path in seen:
            continue
        seen.add(path)
        selected.append({"path": path, "reason": reason or "LLM이 핵심 분석 파일로 선택했습니다."})
        if len(selected) >= 4:
            break
    if not selected:
        raise LLMAnalysisError("Upstage가 유효한 핵심 파일을 선택하지 못했습니다.")
    return selected


def _project_from_llm(project: dict[str, Any], repo: RepoSummary, selected_files: list[SelectedFile] | None = None, *, is_uploaded_file: bool = False) -> ProjectReport:
    repo_id = str(project.get("repo_id") or "").strip()
    if repo_id != repo.id:
        raise LLMAnalysisError(f"Upstage 응답 repo_id가 입력 id와 다릅니다: {repo_id} != {repo.id}")

    dna_raw = project.get("dna") or {}
    report_raw = project.get("report") or {}
    dna = ProjectDNA(
        domain=_as_str_list(dna_raw.get("domain"), max_items=3) or ["미분류"],
        target_user=str(dna_raw.get("target_user") or "대상 사용자 추가 분석 필요"),
        core_problem=str(dna_raw.get("core_problem") or "핵심 문제 정의 추가 분석 필요"),
        core_features=_as_str_list(dna_raw.get("core_features"), max_items=6) or ["핵심 기능 추가 분석 필요"],
        tech_stack=_as_str_list(dna_raw.get("tech_stack"), max_items=8) or repo.languages or [repo.primary_language or "Unknown"],
        summary=str(dna_raw.get("summary") or repo.description or repo.name),
    )

    assets: list[AssetCard] = []
    for asset_raw in project.get("assets") or []:
        if not isinstance(asset_raw, dict):
            continue
        name = str(asset_raw.get("name") or "").strip()
        if not name:
            continue
        assets.append(AssetCard(
            name=name,
            type=str(asset_raw.get("type") or "Asset"),
            reuse_score=_clamp_score(asset_raw.get("reuse_score", 0.5)),
            reusable_for=_as_str_list(asset_raw.get("reusable_for"), max_items=6),
            improvement_needed=_as_str_list(asset_raw.get("improvement_needed"), max_items=6),
        ))

    if not assets:
        raise LLMAnalysisError(f"{repo.name} 분석 결과의 asset이 비어 있습니다.")

    report = DevelopReport(
        limitations=_as_str_list(report_raw.get("limitations"), max_items=8),
        develop_points=_as_str_list(report_raw.get("develop_points"), max_items=10),
        keep=_as_str_list(report_raw.get("keep"), max_items=6),
        modify=_as_str_list(report_raw.get("modify"), max_items=6),
        drop=_as_str_list(report_raw.get("drop"), max_items=6),
        next_builds=_as_str_list(report_raw.get("next_builds"), max_items=8),
        file_tree_suggestion=_as_str_list(report_raw.get("file_tree_suggestion"), max_items=14),
    )

    return ProjectReport(
        project_id=f"file_{repo.id}" if is_uploaded_file else f"repo_{repo.id}",
        repo=repo,
        dna=dna,
        assets=assets,
        report=report,
        selected_files=selected_files or [],
    )


def analyze_repository_with_upstage(repo: RepoSummary, important_files: list[SelectedFile] | None = None) -> ProjectReport:
    data = _call_json(SINGLE_REPO_SYSTEM_PROMPT, _build_single_repo_prompt(repo, important_files or []), temperature=0.2, error_context="Upstage 상세 분석 API")
    return _project_from_llm(data, repo, selected_files=important_files or [], is_uploaded_file=False)


def analyze_uploaded_file_with_upstage(file: UploadedFileSummary) -> ProjectReport:
    data = _call_json(SINGLE_FILE_SYSTEM_PROMPT, _build_single_file_prompt(file), temperature=0.2, error_context="Upstage 파일 상세 분석 API")
    repo = RepoSummary(
        id=file.id,
        name=file.name,
        full_name=file.name,
        html_url="#",
        description=file.mime_type or "Uploaded file",
        primary_language="File",
        languages=["Uploaded File"],
        topics=[],
        readme_text=file.content_excerpt[:2500],
        file_tree=[file.name],
    )
    return _project_from_llm(
        data,
        repo,
        selected_files=[SelectedFile(path=file.name, reason="사용자가 업로드한 원본 파일입니다.", content_excerpt=file.content_excerpt[:2500])],
        is_uploaded_file=True,
    )
