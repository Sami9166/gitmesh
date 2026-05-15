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
    GraphEdge,
    GraphNode,
    ProjectDNA,
    ProjectGraph,
    ProjectPreview,
    ProjectReport,
    RepoSummary,
    ScanResponse,
    SelectedFile,
)


class LLMAnalysisError(RuntimeError):
    """Raised when Upstage/Solar analysis cannot be completed."""


SINGLE_REPO_SYSTEM_PROMPT = """
You are GitMesh, an expert AI product strategist and software architect.
Analyze one GitHub repository deeply and produce Project DNA, reusable asset cards,
and a practical development report.
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


def _repo_payload(
    repo: RepoSummary,
    *,
    include_readme: bool = True,
    include_file_tree: bool = True,
    file_tree_limit: int = 120,
) -> dict[str, Any]:
    readme = repo.readme_text or ""
    payload = {
        "repo_id": repo.id,
        "project_id": f"repo_{repo.id}",
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
        payload["readme_excerpt"] = readme[:4500]
    return payload


def _build_graph_prompt(username: str, repos: list[RepoSummary]) -> str:
    schema = {
        "project_summaries": [
            {
                "project_id": "repo_<repo_id from input>",
                "short_summary": "repo의 용도 1문장",
                "short_domain": ["도메인 키워드 최대 3개"],
            }
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
            {
                "id": "next_1",
                "label": "두 개 이상의 repo를 결합해 만들 수 있는 다음 프로젝트명",
                "project_ids": ["repo_<repo_id>", "repo_<repo_id>"],
                "reason": "왜 이 next build가 가능한지",
            }
        ],
    }

    payload = {
        "task": "Create a lightweight GitMesh repository relationship graph. Do not perform deep repo analysis.",
        "rules": [
            "Use only the repository metadata in the input: name, description, language, topics, stars, forks, and updated_at. Do not assume file contents.",
            "All source_project_id and target_project_id must exactly match one of the input project_id values.",
            "Prefer meaningful relationships over many weak edges. Create at most 8 edges.",
            "If repositories are unrelated, create fewer edges rather than forcing relationships.",
            "Create at most 3 next_builds. A next_build must combine at least 2 repositories.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "github_username": username,
        "repositories": [
            _repo_payload(repo, include_readme=False, include_file_tree=False)
            for repo in repos
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_file_selection_prompt(repo: RepoSummary, candidate_paths: list[str]) -> str:
    schema = {
        "selected_files": [
            {
                "path": "path exactly from candidate_paths",
                "reason": "왜 이 파일이 프로젝트 분석에 중요한지",
            }
        ]
    }
    instruction = {
        "task": "Select up to 8 important files to read before deep GitMesh repo analysis.",
        "rules": [
            "Choose files only from candidate_paths. Paths must match exactly.",
            "Prefer entrypoints, API routes, agent/workflow logic, service modules, UI entrypoints, configuration and dependency files.",
            "Do not select generated files, lock files, images, fonts, binary assets, dependency folders, build outputs, or test snapshots.",
            "If README already explains the repo well, still select source/config files that verify architecture and implementation.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "repository": _repo_payload(repo, include_readme=True, include_file_tree=False),
        "candidate_paths": candidate_paths[:240],
    }
    return json.dumps(instruction, ensure_ascii=False)


def _important_files_payload(
    important_files: list[SelectedFile],
) -> list[dict[str, str]]:
    return [
        {
            "path": file.path,
            "selection_reason": file.reason,
            "content_excerpt": file.content_excerpt[:5000],
        }
        for file in important_files[:8]
    ]


def _build_single_repo_prompt(
    repo: RepoSummary,
    important_files: list[SelectedFile] | None = None,
) -> str:
    schema = {
        "repo_id": "GitHub repo id from input",
        "project_id": "repo_<repo_id>",
        "dna": {
            "domain": ["최대 3개"],
            "target_user": "주요 사용자",
            "core_problem": "이 프로젝트가 해결하려는 핵심 문제",
            "core_features": ["핵심 기능 3~6개"],
            "tech_stack": ["기술 스택 3~8개"],
            "summary": "프로젝트 요약 1~2문장",
        },
        "assets": [
            {
                "name": "재사용 가능한 자산명",
                "type": "Code | UI | Prompt | Data | Architecture | Domain Knowledge | Documentation",
                "reuse_score": 0.0,
                "reusable_for": ["재사용 가능한 프로젝트/도메인"],
                "improvement_needed": ["재사용 전 보완점"],
            }
        ],
        "report": {
            "limitations": ["한계점"],
            "develop_points": ["구체적인 개선/고도화 포인트"],
            "keep": ["유지할 것"],
            "modify": ["수정할 것"],
            "drop": ["버리거나 후순위로 둘 것"],
            "next_builds": ["이 repo에서 이어질 수 있는 다음 프로젝트 후보"],
            "file_tree_suggestion": ["추천 폴더/파일 구조 라인"],
        },
    }

    instruction = {
        "task": "Analyze this GitHub repository and produce GitMesh single-repo JSON.",
        "rules": [
            "Use only repository information in the input. If information is weak, infer cautiously from README, file tree, topics, and languages.",
            "repo_id and project_id must match input values.",
            "Create 2-5 high-quality asset cards.",
            "Create practical develop_points, not generic advice.",
            "file_tree_suggestion must be a concise recommended structure suitable for the repo.",
            "Return strict JSON only.",
        ],
        "output_schema": schema,
        "repository": _repo_payload(
            repo,
            include_readme=True,
            include_file_tree=True,
            file_tree_limit=120,
        ),
        "important_files_read_by_github_contents_api": _important_files_payload(
            important_files or []
        ),
    }
    return json.dumps(instruction, ensure_ascii=False)


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
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=45.0,
        max_retries=0,
    )
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
    """Call Upstage/Solar in JSON object mode and parse the result.

    Without response_format, small models may return JSON-looking text with small syntax
    errors such as missing commas. JSON object mode significantly reduces that failure.
    """
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


def _call_upstage_graph(username: str, repos: list[RepoSummary]) -> dict[str, Any]:
    client, model = _upstage_client()
    return _chat_json_completion(
        client=client,
        model=model,
        system_prompt=GRAPH_SYSTEM_PROMPT,
        user_prompt=_build_graph_prompt(username, repos),
        temperature=0.1,
        error_context="Upstage Graph API",
    )


def _call_upstage_file_selection(
    repo: RepoSummary,
    candidate_paths: list[str],
) -> dict[str, Any]:
    client, model = _upstage_client()
    return _chat_json_completion(
        client=client,
        model=model,
        system_prompt=FILE_SELECT_SYSTEM_PROMPT,
        user_prompt=_build_file_selection_prompt(repo, candidate_paths),
        temperature=0.1,
        error_context="Upstage 파일 선택 API",
    )


def _call_upstage_single(
    repo: RepoSummary,
    important_files: list[SelectedFile] | None = None,
) -> dict[str, Any]:
    client, model = _upstage_client()
    return _chat_json_completion(
        client=client,
        model=model,
        system_prompt=SINGLE_REPO_SYSTEM_PROMPT,
        user_prompt=_build_single_repo_prompt(repo, important_files or []),
        temperature=0.2,
        error_context="Upstage 상세 분석 API",
    )


def _as_str_list(value: Any, *, max_items: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
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


def analyze_project_graph_with_upstage(
    username: str,
    repos: list[RepoSummary],
) -> ScanResponse:
    """Create a lightweight repo relationship graph with Upstage/Solar.

    This runs before deep repository analysis. It should be fast because it only uses
    GitHub metadata and a small file-tree excerpt. No Project DNA / Asset Cards are
    generated here.
    """
    data = _call_upstage_graph(username, repos)
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
                "short_summary": str(
                    summary_by_id.get(_project_id(repo), {}).get("short_summary")
                    or repo.description
                    or ""
                ),
                "short_domain": _as_str_list(
                    summary_by_id.get(_project_id(repo), {}).get("short_domain"),
                    max_items=3,
                ),
            },
        )
        for repo in repos
    ]

    related: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, list[str]] = defaultdict(list)
    edges: list[GraphEdge] = []
    allowed_relations = {
        "similar_to",
        "shares_domain_with",
        "shares_tech_with",
        "can_collaborate_with",
        "can_reuse_asset_from",
        "can_improve_with",
    }

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

        weight = _clamp_score(raw_edge.get("weight", 0.6))
        reason = str(raw_edge.get("reason") or relation).strip()

        edges.append(
            GraphEdge(
                source=source,
                target=target,
                relation=relation,
                weight=weight,
                meta={"reason": reason},
            )
        )
        related[source].add(target)
        related[target].add(source)
        reasons[source].append(reason)
        reasons[target].append(reason)

    # Add NextBuild nodes if Upstage found cross-project opportunities.
    for index, raw_next in enumerate(data.get("next_builds") or [], start=1):
        if not isinstance(raw_next, dict):
            continue

        project_ids = [
            pid
            for pid in _as_str_list(raw_next.get("project_ids"), max_items=5)
            if pid in valid_ids
        ]
        if len(project_ids) < 2:
            continue

        next_id = str(raw_next.get("id") or f"next_{index}").strip()
        if not next_id.startswith("next_"):
            next_id = f"next_{index}"

        label = str(raw_next.get("label") or f"Next Build {index}").strip()
        reason = str(raw_next.get("reason") or "여러 repo를 결합할 수 있습니다.").strip()

        nodes.append(
            GraphNode(
                id=next_id,
                label=label,
                type="NextBuild",
                meta={"reason": reason, "project_ids": project_ids},
            )
        )

        for pid in project_ids:
            edges.append(
                GraphEdge(
                    source=pid,
                    target=next_id,
                    relation="can_create",
                    weight=0.85,
                    meta={"reason": reason},
                )
            )

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

    return ScanResponse(
        username=username,
        projects=previews,
        graph=ProjectGraph(nodes=nodes, edges=edges),
    )


def select_important_files_with_upstage(
    repo: RepoSummary,
    candidate_paths: list[str],
) -> list[dict[str, str]]:
    """Ask Upstage/Solar to select source/config files worth reading.

    This is not a rule-based fallback. Rules are only used before this step by GitHubClient
    to remove unsafe or obviously irrelevant binary/generated paths.
    """
    if not candidate_paths:
        raise LLMAnalysisError("분석할 수 있는 텍스트 파일 경로가 없습니다.")

    data = _call_upstage_file_selection(repo, candidate_paths)
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
        selected.append(
            {
                "path": path,
                "reason": reason or "LLM이 핵심 분석 파일로 선택했습니다.",
            }
        )

        if len(selected) >= 8:
            break

    if not selected:
        raise LLMAnalysisError("Upstage가 유효한 핵심 파일을 선택하지 못했습니다.")

    return selected


def _project_from_llm(
    project: dict[str, Any],
    repo: RepoSummary,
    selected_files: list[SelectedFile] | None = None,
) -> ProjectReport:
    repo_id = str(project.get("repo_id") or "").strip()

    if repo_id != repo.id:
        raise LLMAnalysisError(
            f"Upstage 응답 repo_id가 입력 repo와 다릅니다: {repo_id} != {repo.id}"
        )

    dna_raw = project.get("dna") or {}
    report_raw = project.get("report") or {}

    dna = ProjectDNA(
        domain=_as_str_list(dna_raw.get("domain"), max_items=3) or ["미분류"],
        target_user=str(dna_raw.get("target_user") or "대상 사용자 추가 분석 필요"),
        core_problem=str(dna_raw.get("core_problem") or "핵심 문제 정의 추가 분석 필요"),
        core_features=_as_str_list(dna_raw.get("core_features"), max_items=6)
        or ["핵심 기능 추가 분석 필요"],
        tech_stack=_as_str_list(dna_raw.get("tech_stack"), max_items=8)
        or repo.languages
        or [repo.primary_language or "Unknown"],
        summary=str(dna_raw.get("summary") or repo.description or repo.name),
    )

    assets: list[AssetCard] = []

    for asset_raw in project.get("assets") or []:
        if not isinstance(asset_raw, dict):
            continue

        name = str(asset_raw.get("name") or "").strip()
        if not name:
            continue

        assets.append(
            AssetCard(
                name=name,
                type=str(asset_raw.get("type") or "Asset"),
                reuse_score=_clamp_score(asset_raw.get("reuse_score", 0.5)),
                reusable_for=_as_str_list(asset_raw.get("reusable_for"), max_items=6),
                improvement_needed=_as_str_list(
                    asset_raw.get("improvement_needed"),
                    max_items=6,
                ),
            )
        )

    if not assets:
        raise LLMAnalysisError(f"{repo.name} repository의 asset 분석 결과가 비어 있습니다.")

    report = DevelopReport(
        limitations=_as_str_list(report_raw.get("limitations"), max_items=7),
        develop_points=_as_str_list(report_raw.get("develop_points"), max_items=7),
        keep=_as_str_list(report_raw.get("keep"), max_items=6),
        modify=_as_str_list(report_raw.get("modify"), max_items=6),
        drop=_as_str_list(report_raw.get("drop"), max_items=6),
        next_builds=_as_str_list(report_raw.get("next_builds"), max_items=6),
        file_tree_suggestion=_as_str_list(
            report_raw.get("file_tree_suggestion"),
            max_items=14,
        ),
    )

    return ProjectReport(
        project_id=f"repo_{repo.id}",
        repo=repo,
        dna=dna,
        assets=assets,
        report=report,
        selected_files=selected_files or [],
    )


def analyze_repository_with_upstage(
    repo: RepoSummary,
    important_files: list[SelectedFile] | None = None,
) -> ProjectReport:
    """Analyze a single repository with Upstage/Solar. No rule-based fallback is used."""
    data = _call_upstage_single(repo, important_files or [])
    return _project_from_llm(
        data,
        repo,
        selected_files=important_files or [],
    )