from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Annotated
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .github_client import GitHubClient
from .llm_analyzer import (
    LLMAnalysisError,
    analyze_file_graph_with_upstage,
    analyze_project_graph_with_upstage,
    analyze_repository_with_upstage,
    analyze_uploaded_file_with_upstage,
    select_important_files_with_upstage,
)
from .models import FileScanResponse, RepoAnalyzeResponse, ScanResponse, UploadedFileSummary

load_dotenv()

app = FastAPI(title="GitMesh API", version="0.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_SESSIONS: dict[str, list[UploadedFileSummary]] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/github/scan-user", response_model=ScanResponse)
async def scan_user(
    username: str,
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
) -> ScanResponse:
    client = GitHubClient()
    try:
        scan_limit = min(limit, 10)
        raw_repos = await client.list_public_repos(username=username, limit=scan_limit)
        if not raw_repos:
            raise HTTPException(status_code=404, detail="No public repositories found for this GitHub user.")

        hydrated = await asyncio.gather(
            *(client.hydrate_repo(raw, include_readme=False, include_tree=False) for raw in raw_repos)
        )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_project_graph_with_upstage, username, hydrated),
                timeout=90.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "그래프 생성 시간 초과",
                    "message": "Upstage가 repository 관계 그래프를 90초 안에 생성하지 못했습니다.",
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
    client = GitHubClient()
    try:
        raw = await client.get_repo(full_name)
        repo = await client.hydrate_repo(raw, include_readme=True, include_tree=True, max_files=160)
        candidate_paths = client.selectable_file_paths(repo.file_tree, max_paths=220)

        try:
            selected_file_requests = await asyncio.wait_for(
                asyncio.to_thread(select_important_files_with_upstage, repo, candidate_paths),
                timeout=70.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "핵심 파일 선택 시간 초과",
                    "message": "Upstage가 핵심 파일을 70초 안에 선택하지 못했습니다.",
                },
            ) from exc

        selected_files = await client.read_selected_files(
            full_name=repo.full_name,
            selected_files=selected_file_requests,
            max_files=4,
            max_chars_per_file=2500,
            max_total_chars=10000,
        )
        if not selected_files:
            raise LLMAnalysisError("선택된 핵심 파일을 GitHub Contents API로 읽지 못했습니다.")

        try:
            project = await asyncio.wait_for(
                asyncio.to_thread(analyze_repository_with_upstage, repo, selected_files),
                timeout=150.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "분석 시간 초과",
                    "message": "Upstage 상세 분석이 150초 안에 완료되지 않았습니다.",
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


def _safe_decode_file(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp949", "latin-1"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


@app.post("/files/scan-project", response_model=FileScanResponse)
async def scan_files(files: list[UploadFile] = File(...)) -> FileScanResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Upload up to 20 files.")

    scan_id = f"upload_{int(time.time())}_{uuid4().hex[:8]}"
    summaries: list[UploadedFileSummary] = []

    try:
        for index, upload in enumerate(files, start=1):
            raw = await upload.read()
            if len(raw) > 500_000:
                raw = raw[:500_000]

            text = _safe_decode_file(raw)
            digest = hashlib.sha1(f"{scan_id}:{upload.filename}:{index}".encode("utf-8")).hexdigest()[:12]

            summaries.append(
                UploadedFileSummary(
                    id=digest,
                    name=upload.filename or f"uploaded_file_{index}",
                    size=len(raw),
                    mime_type=upload.content_type,
                    content_excerpt=text[:12000],
                )
            )

        UPLOAD_SESSIONS[scan_id] = summaries

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_file_graph_with_upstage, scan_id, summaries),
                timeout=90.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "title": "파일 그래프 생성 시간 초과",
                    "message": "Upstage가 파일 관계 그래프를 90초 안에 생성하지 못했습니다.",
                },
            ) from exc

    except HTTPException:
        raise
    except LLMAnalysisError as exc:
        raise HTTPException(status_code=502, detail={"title": "LLM 파일 그래프 생성 실패", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"title": "파일 스캔 실패", "message": str(exc)}) from exc


@app.post("/files/analyze-file", response_model=RepoAnalyzeResponse)
async def analyze_file(scan_id: str, file_id: str) -> RepoAnalyzeResponse:
    files = UPLOAD_SESSIONS.get(scan_id)
    if not files:
        raise HTTPException(status_code=404, detail="Upload session not found. Please upload files again.")

    target = next((file for file in files if file.id == file_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Uploaded file not found in this session.")

    try:
        project = await asyncio.wait_for(
            asyncio.to_thread(analyze_uploaded_file_with_upstage, target),
            timeout=150.0,
        )
        return RepoAnalyzeResponse(project=project)

    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "title": "파일 분석 시간 초과",
                "message": "Upstage 파일 상세 분석이 150초 안에 완료되지 않았습니다.",
            },
        ) from exc
    except LLMAnalysisError as exc:
        raise HTTPException(status_code=502, detail={"title": "LLM 파일 분석 실패", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"title": "파일 분석 실패", "message": str(exc)}) from exc


@app.get("/github/{username}/repos")
async def list_repos(username: str, limit: Annotated[int, Query(ge=1, le=10)] = 10) -> list[dict]:
    client = GitHubClient()
    try:
        repos = await client.list_public_repos(username=username, limit=min(limit, 10))
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
