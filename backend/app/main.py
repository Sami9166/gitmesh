from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .llm_analyzer import (
    LLMAnalysisError,
    analyze_project_graph_with_upstage,
    analyze_repository_with_upstage,
    select_important_files_with_upstage,
)
from .github_client import GitHubClient
from .models import RepoAnalyzeResponse, ScanResponse

load_dotenv()

app = FastAPI(title="GitMesh API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/github/scan-user", response_model=ScanResponse)
async def scan_user(
    username: str,
    limit: Annotated[int, Query(ge=1, le=5)] = 5,
) -> ScanResponse:
    """Fetch top 5 public repositories and build a lightweight Upstage-powered repo graph.

    This endpoint does not read README or source file contents. It only uses GitHub
    metadata such as name, description, language, topics, stars, forks and updated_at.
    """
    client = GitHubClient()
    try:
        scan_limit = min(limit, 5)
        raw_repos = await client.list_public_repos(username=username, limit=scan_limit)
        if not raw_repos:
            raise HTTPException(status_code=404, detail="No public repositories found for this GitHub user.")

        # Fast path: metadata + languages only. No README, no file tree, no source files.
        hydrated = await asyncio.gather(
            *(client.hydrate_repo(raw, include_readme=False, include_tree=False) for raw in raw_repos)
        )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_project_graph_with_upstage, username=username, repos=hydrated),
                timeout=50.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "그래프 생성 시간 초과",
                    "message": "Upstage가 repository 관계 그래프를 50초 안에 생성하지 못했습니다. 잠시 후 다시 시도해주세요.",
                },
            ) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMAnalysisError as exc:
        raise HTTPException(status_code=502, detail={"title": "LLM 그래프 생성 실패", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"title": "GitHub 스캔 실패", "message": str(exc)}) from exc


@app.post("/github/analyze-repo", response_model=RepoAnalyzeResponse)
async def analyze_repo(full_name: str) -> RepoAnalyzeResponse:
    """Run deep Upstage analysis only for the repository selected by the user.

    Flow:
    1. Read README and file tree.
    2. Ask Upstage which source/config files are important.
    3. Read only those selected files through GitHub Contents API.
    4. Ask Upstage to create Project DNA, Asset Cards and Develop Report.
    """
    client = GitHubClient()
    try:
        raw = await client.get_repo(full_name)
        repo = await client.hydrate_repo(raw, include_readme=True, include_tree=True, max_files=240)
        candidate_paths = client.selectable_file_paths(repo.file_tree, max_paths=240)

        try:
            selected_file_requests = await asyncio.wait_for(
                asyncio.to_thread(select_important_files_with_upstage, repo, candidate_paths),
                timeout=45.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "핵심 파일 선택 시간 초과",
                    "message": "Upstage가 핵심 파일을 45초 안에 선택하지 못했습니다. 잠시 후 다시 시도해주세요.",
                },
            ) from exc

        selected_files = await client.read_selected_files(
            full_name=repo.full_name,
            selected_files=selected_file_requests,
            max_files=8,
            max_chars_per_file=5000,
            max_total_chars=30000,
        )
        if not selected_files:
            raise LLMAnalysisError("선택된 핵심 파일을 GitHub Contents API로 읽지 못했습니다.")

        try:
            project = await asyncio.wait_for(
                asyncio.to_thread(analyze_repository_with_upstage, repo, selected_files),
                timeout=90.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "분석 시간 초과",
                    "message": "Upstage 분석이 90초 안에 완료되지 않았습니다. 잠시 후 다시 시도해주세요.",
                },
            ) from exc
        return RepoAnalyzeResponse(project=project)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMAnalysisError as exc:
        raise HTTPException(status_code=502, detail={"title": "LLM 분석 실패", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"title": "Repository 분석 실패", "message": str(exc)}) from exc


@app.get("/github/{username}/repos")
async def list_repos(username: str, limit: Annotated[int, Query(ge=1, le=5)] = 5) -> list[dict]:
    client = GitHubClient()
    try:
        repos = await client.list_public_repos(username=username, limit=min(limit, 5))
        return [
            {
                "id": str(repo["id"]),
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": repo.get("description"),
                "html_url": repo["html_url"],
                "language": repo.get("language"),
                "stars": repo.get("stargazers_count", 0),
                "updated_at": repo.get("updated_at"),
            }
            for repo in repos
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
