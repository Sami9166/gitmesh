from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import httpx
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

app = FastAPI(title="GitMesh API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_SESSIONS: dict[str, list[UploadedFileSummary]] = {}

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = BASE_DIR / "data" / "upload_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".csv",
    ".xml",
    ".sql",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".dart",
    ".sh",
    ".bat",
    ".ps1",
    ".dockerfile",
    ".gitignore",
}

DOCUMENT_PARSE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".docx",
    ".pptx",
    ".xlsx",
    ".hwp",
}

TEXT_MIME_PREFIXES = ("text/",)

TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/javascript",
    "application/typescript",
}

DOCUMENT_PARSE_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/gif",
    "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/haansofthwp",
    "application/x-hwp",
}

MAX_TEXT_BYTES = 500_000
MAX_PARSE_BYTES = 50_000_000
MAX_EXCERPT_CHARS = 12_000


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
            raise HTTPException(
                status_code=404,
                detail="No public repositories found for this GitHub user.",
            )

        hydrated = await asyncio.gather(
            *(
                client.hydrate_repo(
                    raw,
                    include_readme=False,
                    include_tree=False,
                )
                for raw in raw_repos
            )
        )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    analyze_project_graph_with_upstage,
                    username,
                    hydrated,
                ),
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
        raise HTTPException(
            status_code=502,
            detail={"title": "LLM 그래프 생성 실패", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"title": "GitHub 스캔 실패", "message": str(exc)},
        ) from exc


@app.post("/github/analyze-repo", response_model=RepoAnalyzeResponse)
async def analyze_repo(full_name: str) -> RepoAnalyzeResponse:
    client = GitHubClient()

    try:
        raw = await client.get_repo(full_name)
        repo = await client.hydrate_repo(
            raw,
            include_readme=True,
            include_tree=True,
            max_files=160,
        )

        candidate_paths = client.selectable_file_paths(repo.file_tree, max_paths=220)

        try:
            selected_file_requests = await asyncio.wait_for(
                asyncio.to_thread(
                    select_important_files_with_upstage,
                    repo,
                    candidate_paths,
                ),
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
                asyncio.to_thread(
                    analyze_repository_with_upstage,
                    repo,
                    selected_files,
                ),
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
        raise HTTPException(
            status_code=502,
            detail={"title": "LLM 분석 실패", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"title": "Repository 분석 실패", "message": str(exc)},
        ) from exc


def _file_extension(filename: str | None) -> str:
    if not filename:
        return ""

    normalized = filename.lower().strip()

    if normalized == "dockerfile":
        return ".dockerfile"

    _, ext = os.path.splitext(normalized)
    return ext


def _is_text_file(filename: str | None, mime_type: str | None) -> bool:
    ext = _file_extension(filename)

    if ext in TEXT_EXTENSIONS:
        return True

    if not mime_type:
        return False

    normalized_mime = mime_type.lower()

    if normalized_mime in TEXT_MIME_TYPES:
        return True

    return any(normalized_mime.startswith(prefix) for prefix in TEXT_MIME_PREFIXES)


def _is_document_parse_file(filename: str | None, mime_type: str | None) -> bool:
    ext = _file_extension(filename)

    if ext in DOCUMENT_PARSE_EXTENSIONS:
        return True

    if not mime_type:
        return False

    return mime_type.lower() in DOCUMENT_PARSE_MIME_TYPES


def _safe_decode_file(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp949", "latin-1"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue

    return raw.decode("utf-8", errors="ignore")


def _summary_to_dict(summary: UploadedFileSummary) -> dict:
    if hasattr(summary, "model_dump"):
        return summary.model_dump()

    return summary.dict()


def _save_upload_session(scan_id: str, summaries: list[UploadedFileSummary]) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "scan_id": scan_id,
        "created_at": int(time.time()),
        "files": [_summary_to_dict(summary) for summary in summaries],
    }

    session_path = SESSION_DIR / f"{scan_id}.json"
    session_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_upload_session(scan_id: str) -> list[UploadedFileSummary] | None:
    if scan_id in UPLOAD_SESSIONS:
        return UPLOAD_SESSIONS[scan_id]

    session_path = SESSION_DIR / f"{scan_id}.json"

    if not session_path.exists():
        return None

    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        files = payload.get("files", [])

        summaries = [UploadedFileSummary(**item) for item in files]
        UPLOAD_SESSIONS[scan_id] = summaries

        return summaries

    except Exception:
        return None


def _collect_strings_by_key(obj: Any, target_keys: set[str]) -> list[str]:
    values: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = str(key).lower()

            if normalized_key in target_keys and isinstance(value, str):
                text = value.strip()
                if text:
                    values.append(text)

            values.extend(_collect_strings_by_key(value, target_keys))

    elif isinstance(obj, list):
        for item in obj:
            values.extend(_collect_strings_by_key(item, target_keys))

    return values


def _extract_text_from_upstage_response(data: dict[str, Any]) -> str:
    """
    Upstage Document Parse 응답 구조는 옵션이나 버전에 따라 조금씩 달라질 수 있다.
    그래서 markdown, text, html, content, result, document 필드를 넓게 탐색한다.
    """

    direct_priority_paths = [
        ("markdown",),
        ("text",),
        ("html",),
        ("content", "markdown"),
        ("content", "text"),
        ("content", "html"),
        ("result", "markdown"),
        ("result", "text"),
        ("result", "html"),
        ("document", "markdown"),
        ("document", "text"),
        ("document", "html"),
    ]

    for path in direct_priority_paths:
        current: Any = data

        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)

        if isinstance(current, str) and current.strip():
            return current.strip()

    markdown_values = _collect_strings_by_key(data, {"markdown"})
    if markdown_values:
        return "\n\n".join(markdown_values).strip()

    text_values = _collect_strings_by_key(data, {"text"})
    if text_values:
        return "\n\n".join(text_values).strip()

    html_values = _collect_strings_by_key(data, {"html"})
    if html_values:
        return "\n\n".join(html_values).strip()

    return ""


async def _parse_with_upstage_document_parse(
    *,
    filename: str,
    raw: bytes,
    mime_type: str | None,
) -> str:
    api_key = os.getenv("UPSTAGE_API_KEY")

    if not api_key:
        raise LLMAnalysisError("UPSTAGE_API_KEY가 설정되어 있지 않아 Document Parse를 실행할 수 없습니다.")

    parse_url = os.getenv(
        "UPSTAGE_DOCUMENT_PARSE_URL",
        "https://api.upstage.ai/v1/document-digitization",
    )
    parse_model = os.getenv("UPSTAGE_PARSE_MODEL", "document-parse")
    parse_mode = os.getenv("UPSTAGE_PARSE_MODE", "standard")
    parse_ocr = os.getenv("UPSTAGE_PARSE_OCR", "auto")

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    files = {
        "document": (
            filename,
            raw,
            mime_type or "application/octet-stream",
        )
    }

    form_data: dict[str, str] = {
        "model": parse_model,
    }

    if parse_mode:
        form_data["mode"] = parse_mode

    if parse_ocr:
        form_data["ocr"] = parse_ocr

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            parse_url,
            headers=headers,
            files=files,
            data=form_data,
        )

    if response.status_code >= 400:
        error_text = response.text[:1000]
        raise LLMAnalysisError(
            f"Document Parse API 호출 실패: status={response.status_code}, body={error_text}"
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise LLMAnalysisError("Document Parse API 응답을 JSON으로 파싱하지 못했습니다.") from exc

    parsed_text = _extract_text_from_upstage_response(payload)

    if not parsed_text:
        raise LLMAnalysisError("Document Parse API 응답에서 markdown/text/html을 찾지 못했습니다.")

    return parsed_text


async def _parse_uploaded_file_to_text(
    *,
    filename: str,
    raw: bytes,
    mime_type: str | None,
) -> str:
    """
    GitMesh local upload parser.

    1. 코드/README/JSON/YAML 같은 텍스트 파일은 기존처럼 decode.
    2. PDF/PPTX/DOCX/XLSX/HWP/이미지는 Upstage Document Parse 사용.
    3. Document Parse 실패 시 전체 scan이 죽지 않도록 fallback 메시지를 반환.
    """

    if _is_text_file(filename, mime_type):
        sliced = raw[:MAX_TEXT_BYTES]
        return _safe_decode_file(sliced)

    if _is_document_parse_file(filename, mime_type):
        if len(raw) > MAX_PARSE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "title": "파일 크기 초과",
                    "message": f"{filename} 파일이 Document Parse 처리 제한보다 큽니다.",
                },
            )

        try:
            return await _parse_with_upstage_document_parse(
                filename=filename,
                raw=raw,
                mime_type=mime_type,
            )
        except LLMAnalysisError as exc:
            fallback = _safe_decode_file(raw[:MAX_TEXT_BYTES]).strip()

            if fallback:
                return (
                    f"[Document Parse failed: {exc}]\n\n"
                    f"[Fallback decoded text]\n{fallback}"
                )

            return (
                f"[Document Parse failed: {exc}]\n\n"
                "이 파일은 현재 텍스트로 변환되지 않았습니다. "
                "파일명과 MIME type만 기반으로 제한적인 분석을 수행합니다."
            )

    sliced = raw[:MAX_TEXT_BYTES]
    decoded = _safe_decode_file(sliced).strip()

    if decoded:
        return decoded

    return (
        "이 파일은 현재 GitMesh에서 텍스트로 해석하기 어려운 형식입니다. "
        "PDF, DOCX, PPTX, XLSX, HWP 또는 텍스트 기반 코드/문서 파일을 업로드하는 것을 권장합니다."
    )


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
            filename = upload.filename or f"uploaded_file_{index}"
            mime_type = upload.content_type
            original_size = len(raw)

            text = await _parse_uploaded_file_to_text(
                filename=filename,
                raw=raw,
                mime_type=mime_type,
            )

            digest = hashlib.sha1(
                f"{scan_id}:{filename}:{index}".encode("utf-8")
            ).hexdigest()[:12]

            summaries.append(
                UploadedFileSummary(
                    id=digest,
                    name=filename,
                    size=original_size,
                    mime_type=mime_type,
                    content_excerpt=text[:MAX_EXCERPT_CHARS],
                )
            )

        UPLOAD_SESSIONS[scan_id] = summaries
        _save_upload_session(scan_id, summaries)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    analyze_file_graph_with_upstage,
                    scan_id,
                    summaries,
                ),
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
        raise HTTPException(
            status_code=502,
            detail={"title": "LLM 파일 그래프 생성 실패", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"title": "파일 스캔 실패", "message": str(exc)},
        ) from exc


@app.post("/files/analyze-file", response_model=RepoAnalyzeResponse)
async def analyze_file(scan_id: str, file_id: str) -> RepoAnalyzeResponse:
    files = _load_upload_session(scan_id)

    if not files:
        raise HTTPException(
            status_code=404,
            detail="Upload session not found. Please upload files again.",
        )

    target = next((file for file in files if file.id == file_id), None)

    if not target:
        raise HTTPException(
            status_code=404,
            detail="Uploaded file not found in this session.",
        )

    try:
        project = await asyncio.wait_for(
            asyncio.to_thread(
                analyze_uploaded_file_with_upstage,
                target,
            ),
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
        raise HTTPException(
            status_code=502,
            detail={"title": "LLM 파일 분석 실패", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"title": "파일 분석 실패", "message": str(exc)},
        ) from exc


@app.get("/github/{username}/repos")
async def list_repos(
    username: str,
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
) -> list[dict]:
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